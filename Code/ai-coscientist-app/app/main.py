"""FastAPI application main module."""

import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from litellm import acompletion
from pydantic import BaseModel, Field
from rich.console import Console

from open_coscientist import HypothesisGenerator

# Load .env file before importing settings
load_dotenv()

from .config import settings

# Configure logging
# Set root logger to INFO to suppress DEBUG logs from dependencies (httpx, etc.)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Set application loggers (viewer and open_coscientist) to DEBUG if debug mode is enabled
logger = logging.getLogger(__name__)
coscientist_logger = logging.getLogger("open_coscientist")
if settings.debug:
    logger.setLevel(logging.DEBUG)
    coscientist_logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)
    coscientist_logger.setLevel(logging.INFO)
console = Console()

# Set environment variables for open-coscientist
# LiteLLM uses provider-specific env vars (GEMINI_API_KEY, OPENAI_API_KEY, etc.)
if settings.gemini_api_key:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
if settings.coscientist_cache_enabled:
    os.environ["COSCIENTIST_CACHE_ENABLED"] = "true"
if settings.coscientist_cache_dir:
    os.environ["COSCIENTIST_CACHE_DIR"] = settings.coscientist_cache_dir
if settings.coscientist_lit_review_papers_count:
    os.environ["COSCIENTIST_LIT_REVIEW_PAPERS_COUNT"] = str(settings.coscientist_lit_review_papers_count)

# Set MCP server URL if available
if settings.mcp_server_url:
    os.environ["MCP_SERVER_URL"] = settings.mcp_server_url
    logger.info(f"mcp_server_url configured: {settings.mcp_server_url}")
else:
    logger.info("mcp_server_url not set - literature review will be disabled")


# Global generator instance (can be reused)
_generator: HypothesisGenerator | None = None

# Active generation tasks
# task_id -> {"generator": AsyncGenerator, "cancelled": asyncio.Event}
# Protected by lock for thread-safe concurrent access
_active_tasks: dict[str, dict] = {}
_active_tasks_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown.
    """
    global _generator

    # Startup
    logger.info("Starting Open CoScientist server...")
    logger.info(f"Model: {settings.model_name}")
    logger.info(f"Max iterations: {settings.max_iterations}")
    logger.info(f"Initial hypotheses count: {settings.initial_hypotheses_count}")
    logger.info(f"Evolution max count: {settings.evolution_max_count}")
    if settings.tools_config:
        logger.info(f"Tools config: {settings.tools_config}")
    else:
        logger.info("Tools config: not set (generator defaults)")

    _generator = HypothesisGenerator(
        model_name=settings.model_name,
        max_iterations=settings.max_iterations,
        initial_hypotheses_count=settings.initial_hypotheses_count,
        evolution_max_count=settings.evolution_max_count,
        enable_cache=settings.coscientist_cache_enabled,
        cache_dir=settings.coscientist_cache_dir if settings.coscientist_cache_dir else None,
        tools_config=settings.tools_config,
    )

    yield

    # Shutdown
    logger.info("Shutting down Open CoScientist server...")


app = FastAPI(
    title="Open CoScientist API",
    description="FastAPI server for AI hypothesis generation using Open CoScientist",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class GenerateRequest(BaseModel):
    """Request model for hypothesis generation."""

    research_goal: str = Field(..., description="The research question or goal")
    model_name: str | None = Field(
        None, description="Override default model name (optional)"
    )
    max_iterations: int | None = Field(
        None, description="Override default max iterations (optional)"
    )
    initial_hypotheses_count: int | None = Field(
        None, description="Override default initial hypotheses count (optional)"
    )
    evolution_max_count: int | None = Field(
        None, description="Override default evolution max count (optional)"
    )
    enable_literature_review_node: bool | None = Field(
        None,
        description="Whether to include literature review node (default: auto-detect based on mcp server availability)",
    )


class GenerateResponse(BaseModel):
    """Response model for hypothesis generation (non streaming)."""
    hypotheses: list[dict]
    meta_review: dict
    research_plan: dict
    tournament_matchups: list[dict]
    evolution_details: list[dict]
    execution_time: float
    metrics: dict


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    model_name: str


class ConfigResponse(BaseModel):
    """Configuration defaults response."""
    max_iterations: int
    initial_hypotheses_count: int
    evolution_max_count: int


class SystemStatusResponse(BaseModel):
    """System availability status response."""

    mcp_available: bool = Field(..., description="whether mcp server is available")
    pubmed_available: bool = Field(..., description="whether pubmed api is available")
    literature_review_available: bool = Field(
        ..., description="whether literature review is available (requires both mcp and pubmed)"
    )
    mcp_server_url: str = Field(..., description="configured mcp server url")


class ParsedResearchGoal(BaseModel):
    """Parsed structure from user input."""

    research_goal: str = Field(..., description="The core research question or goal")
    preferences: str | None = Field(None, description="Desired approach or focus")
    attributes: list[str] | None = Field(None, description="Key qualities to prioritize")
    constraints: list[str] | None = Field(None, description="Requirements or boundaries")
    user_inputs: dict | None = Field(None, description="Additional user-provided context")
    enable_literature_review_node: bool | None = Field(
        None, description="Whether to include literature review node (optional, auto-detect if not specified)"
    )


def _get_parse_cache_dir() -> Path:
    """get the viewer parse cache directory."""
    cache_dir = os.getenv("COSCIENTIST_CACHE_DIR", ".coscientist_cache")
    parse_cache_dir = Path(cache_dir) / "viewer-cache"
    parse_cache_dir.mkdir(parents=True, exist_ok=True)
    return parse_cache_dir


def _get_cached_parse(raw_input: str) -> ParsedResearchGoal | None:
    """get cached parsed research goal if available."""
    try:
        cache_dir = _get_parse_cache_dir()
        cache_key = hashlib.md5(raw_input.encode()).hexdigest()
        cache_file = cache_dir / f"{cache_key}.json"

        if cache_file.exists():
            with open(cache_file, "r") as f:
                cached_data = json.load(f)
            logger.info(f"parse cache hit for input: {raw_input[:50]}...")
            return ParsedResearchGoal(**cached_data)
    except Exception as e:
        logger.warning(f"failed to read parse cache: {e}")

    return None


def _cache_parse(raw_input: str, parsed: ParsedResearchGoal) -> None:
    """cache parsed research goal to disk."""
    try:
        cache_dir = _get_parse_cache_dir()
        cache_key = hashlib.md5(raw_input.encode()).hexdigest()
        cache_file = cache_dir / f"{cache_key}.json"

        with open(cache_file, "w") as f:
            json.dump(parsed.model_dump(), f, indent=2)

    except Exception as e:
        logger.warning(f"Failed to cache parse: {e}")


async def parse_research_goal_input(raw_input: str) -> ParsedResearchGoal:
    """Parse broad research goal input using LLM with JSON schema."""

    # check cache first
    cached = _get_cached_parse(raw_input)
    if cached is not None:
        return cached

    prompt = f"""Parse the following research goal input and extract structured information.

User Input:
{raw_input}

Extract:
- research_goal: The core research question or goal (required, should be a clear question or statement)
- preferences: Any stated preferences about approach or focus (optional, single string)
- attributes: Key qualities to prioritize like novelty, feasibility, clinical relevance, etc. (optional, list of strings)
- constraints: Requirements or boundaries like "should be testable within 5 years", "must be ethically sound" (optional, list of strings)
- user_inputs: Any related hypotheses, literature references, or context provided (optional, object with keys: starting_hypotheses (list), literature (list))

If a field is not clearly present in the input, omit it or return null/empty.
Return ONLY valid JSON matching the schema."""

    response_schema = {
        "type": "object",
        "properties": {
            "research_goal": {
                "type": "string",
                "description": "The core research question or goal"
            },
            "preferences": {
                "type": "string",
                "description": "Desired approach or focus (empty string if not present)"
            },
            "attributes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key qualities to prioritize (empty array if not present)"
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Requirements or boundaries (empty array if not present)"
            },
            "user_inputs": {
                "type": "object",
                "properties": {
                    "starting_hypotheses": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "literature": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "description": "Additional user-provided context"
            }
        },
        "required": ["research_goal"]
    }

    try:
        response = await acompletion(
            model="gemini/gemini-2.5-flash",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": {"name": "research_goal_parser", "schema": response_schema}}
        )

        parsed_json = json.loads(response.choices[0].message.content)

        # convert empty strings/arrays to None for optional fields
        if "preferences" in parsed_json and not parsed_json["preferences"]:
            parsed_json["preferences"] = None
        if "attributes" in parsed_json and not parsed_json["attributes"]:
            parsed_json["attributes"] = None
        if "constraints" in parsed_json and not parsed_json["constraints"]:
            parsed_json["constraints"] = None
        if "user_inputs" in parsed_json and not parsed_json["user_inputs"]:
            parsed_json["user_inputs"] = None

        logger.info(f"Parsed research goal: {parsed_json}")
        parsed_goal = ParsedResearchGoal(**parsed_json)

        # cache the result
        _cache_parse(raw_input, parsed_goal)

        return parsed_goal

    except Exception as e:
        logger.error(f"Error parsing research goal with LLM: {e}", exc_info=True)
        # Fallback: treat entire input as research_goal
        logger.warning("Falling back to using entire input as research_goal")
        fallback_goal = ParsedResearchGoal(research_goal=raw_input)

        # cache the fallback too
        _cache_parse(raw_input, fallback_goal)

        return fallback_goal


@app.get("/", tags=["root"])
async def root():
    """Root endpoint."""
    return {
        "message": "Open CoScientist API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        model_name=settings.model_name,
    )


@app.get("/config", response_model=ConfigResponse, tags=["config"])
async def get_config():
    """Get default configuration values."""
    return ConfigResponse(
        max_iterations=settings.max_iterations,
        initial_hypotheses_count=settings.initial_hypotheses_count,
        evolution_max_count=settings.evolution_max_count,
    )


@app.get("/status", response_model=SystemStatusResponse, tags=["system"])
async def get_system_status():
    """
    Check system availability for literature review features.

    returns availability status for mcp server and pubmed api.
    """
    from open_coscientist.mcp_client import check_mcp_available
    from open_coscientist.mcp_client import check_pubmed_available_via_mcp

    # check availability of external services
    mcp_available = await check_mcp_available()
    pubmed_available = await check_pubmed_available_via_mcp()

    return SystemStatusResponse(
        mcp_available=mcp_available,
        pubmed_available=pubmed_available,
        literature_review_available=mcp_available,
        mcp_server_url=settings.mcp_server_url,
    )


@app.post("/generate", response_model=GenerateResponse, tags=["hypotheses"])
async def generate_hypotheses(request: GenerateRequest):
    """
    Generate hypotheses for a research goal.

    This endpoint runs the full hypothesis generation workflow and returns
    the complete results when finished.
    """
    if _generator is None:
        raise HTTPException(status_code=503, detail="Generator not initialized")

    try:
        # Use request overrides or fall back to settings/defaults
        generator = _generator
        if any(
            [
                request.model_name,
                request.max_iterations is not None,
                request.initial_hypotheses_count is not None,
                request.evolution_max_count is not None,
            ]
        ):
            # Capture values with default fallbacks
            model_name = request.model_name or settings.model_name
            max_iterations = (
                request.max_iterations
                if request.max_iterations is not None
                else settings.max_iterations
            )
            initial_hypotheses_count = (
                request.initial_hypotheses_count
                if request.initial_hypotheses_count is not None
                else settings.initial_hypotheses_count
            )
            evolution_max_count = (
                request.evolution_max_count
                if request.evolution_max_count is not None
                else settings.evolution_max_count
            )
            enable_cache = settings.coscientist_cache_enabled
            cache_dir = (
                settings.coscientist_cache_dir
                if settings.coscientist_cache_dir
                else None
            )

            # Log all values being used
            logger.info("Creating HypothesisGenerator (no streaming) with parameters:")
            logger.info(f"  model_name: {model_name}")
            logger.info(f"  max_iterations: {max_iterations}")
            logger.info(f"  initial_hypotheses_count: {initial_hypotheses_count}")
            logger.info(f"  evolution_max_count: {evolution_max_count}")
            logger.info(f"  enable_cache: {enable_cache}")
            logger.info(f"  cache_dir: {cache_dir}")

            # Create a new generator with overrides
            generator = HypothesisGenerator(
                model_name=model_name,
                max_iterations=max_iterations,
                initial_hypotheses_count=initial_hypotheses_count,
                evolution_max_count=evolution_max_count,
                enable_cache=enable_cache,
                cache_dir=cache_dir,
                tools_config=settings.tools_config,
            )

        # generate run_id for non-streaming endpoint
        import uuid
        run_id = str(uuid.uuid4())

        # prepare opts with enable_literature_review_node if specified
        opts = {}
        if request.enable_literature_review_node is not None:
            opts["enable_literature_review_node"] = request.enable_literature_review_node

        result = await generator.generate_hypotheses(
            research_goal=request.research_goal,
            opts=opts if opts else None,
            run_id=run_id
        )

        return GenerateResponse(**result)

    except Exception as e:
        logger.error(f"Error generating hypotheses: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


async def stream_generator(
    parsed_goal: ParsedResearchGoal,
    generator: HypothesisGenerator,
    cancelled_event: asyncio.Event,
    task_id: str,
) -> AsyncGenerator[str, None]:
    """Generate Server-Sent Events stream from hypothesis generation."""
    try:
        console.print("\n[bold yellow]═══ sse stream starting ═══[/bold yellow]")
        console.print(f"[cyan]research goal:[/cyan] {parsed_goal.research_goal[:100]}...")

        # Send initial event with parsed goal data
        start_event = {
            "type": "start",
            "message": "starting hypothesis generation...",
            "parsed_goal": {
                "research_goal": parsed_goal.research_goal,
                "preferences": parsed_goal.preferences,
                "attributes": parsed_goal.attributes,
                "constraints": parsed_goal.constraints,
                "user_inputs": parsed_goal.user_inputs,
            }
        }
        console.print("[green]→ Sending sse event:[/green] [dim]type=start[/dim]")
        yield f"data: {json.dumps(start_event)}\n\n"

        # Track iteration for UI grouping
        # The library's current_iteration doesn't increment until AFTER proximity
        # But UI needs to group meta_review/evolve/etc under the next iteration
        has_seen_meta_review = False
        ui_iteration = 0  # For UI display (0 = initial, 1+ = iterations)

        # pass all parsed fields to the generator
        opts = {
            "preferences": parsed_goal.preferences,
            "attributes": parsed_goal.attributes,
            "constraints": parsed_goal.constraints,
            "user_inputs": parsed_goal.user_inputs,
            "enable_tool_calling_generation": True,
        }

        # add enable_literature_review_node if specified
        if parsed_goal.enable_literature_review_node is not None:
            opts["enable_literature_review_node"] = parsed_goal.enable_literature_review_node

        async for node_name, state in generator.generate_hypotheses(
            research_goal=parsed_goal.research_goal,
            opts=opts,
            run_id=task_id,
            stream=True
        ):
            # Check if cancelled before processing each node
            if cancelled_event.is_set():
                console.print("[red]✗ generation cancelled by user[/red]")
                logger.info("generation cancelled by user")
                yield "data: {\"type\": \"cancelled\", \"message\": \"generation cancelled\"}\n\n"
                return

            # Format as Server-Sent Event

            # Determine UI iteration based on workflow phase
            # Initial generation (iteration 0): supervisor → literature_review → generate → reflection → review → ranking
            # Evolution iterations (1+): meta_review → evolve → review → ranking → proximity

            if node_name == "meta_review":
                # Entering an evolution iteration
                has_seen_meta_review = True
                ui_iteration = state.get("current_iteration", 0) + 1
            elif not has_seen_meta_review:
                # Still in initial generation
                ui_iteration = 0
            # else: keep current ui_iteration (we're in an evolution cycle)

            # Add iteration info to state
            state["ui_iteration"] = ui_iteration
            state["iteration_phase"] = "initial" if ui_iteration == 0 else f"iteration_{ui_iteration}"

            event_data = {
                "type": "update",
                "node": node_name,
                "state": state,
            }

            console.print(f"[green]→ Sending sse event:[/green] [cyan]type=update, node={node_name}[/cyan]")

            yield f"data: {json.dumps(event_data)}\n\n"

            # Small delay to prevent overwhelming the client
            await asyncio.sleep(0.1)

        # Check if cancelled before sending completion
        if cancelled_event.is_set():
            console.print("[red]Generation cancelled by user[/red]")
            yield "data: {\"type\": \"cancelled\", \"message\": \"generation cancelled\"}\n\n"
            return

        # Send completion event
        console.print("[bold green]Sending sse event: type=complete[/bold green]")
        yield "data: {\"type\": \"complete\", \"message\": \"hypothesis generation completed\"}\n\n"

    except asyncio.CancelledError:
        console.print("[red]Generation cancelled (CancelledError)[/red]")
        yield "data: {\"type\": \"cancelled\", \"message\": \"generation cancelled\"}\n\n"
    except Exception as e:
        logger.error(f"error in streaming: {e}", exc_info=True)
        error_data = {"type": "error", "message": str(e)}
        yield f"data: {json.dumps(error_data)}\n\n"


@app.post("/generate/start", tags=["hypotheses"])
async def start_generation(request: GenerateRequest):
    """
    Start hypothesis generation and return a task ID.

    Use the returned task_id to subscribe to the SSE stream via GET /generate/stream/{task_id}
    """
    if _generator is None:
        raise HTTPException(status_code=503, detail="Generator not initialized")

    try:
        import uuid
        task_id = str(uuid.uuid4())

        # Parse the research goal input to extract structured information
        logger.info(f"parsing research goal input for task {task_id}")
        parsed_goal = await parse_research_goal_input(request.research_goal)

        # override with explicit enable_literature_review_node from request if provided
        if request.enable_literature_review_node is not None:
            parsed_goal.enable_literature_review_node = request.enable_literature_review_node

        logger.info(f"parsed goal - core: '{parsed_goal.research_goal[:100]}...'")
        if parsed_goal.preferences:
            logger.info(f"  preferences: {parsed_goal.preferences}")
        if parsed_goal.attributes:
            logger.info(f"  attributes: {parsed_goal.attributes}")
        if parsed_goal.constraints:
            logger.info(f"  constraints: {parsed_goal.constraints}")
        if parsed_goal.user_inputs:
            logger.info(f"  user inputs: {parsed_goal.user_inputs}")
        if parsed_goal.enable_literature_review_node is not None:
            logger.info(f"  enable_literature_review_node: {parsed_goal.enable_literature_review_node}")

        # Use request overrides or fall back to settings/defaults
        generator = _generator
        if any(
            [
                request.model_name,
                request.max_iterations is not None,
                request.initial_hypotheses_count is not None,
                request.evolution_max_count is not None,
            ]
        ):
            # Capture values with default fallbacks
            model_name = request.model_name or settings.model_name
            max_iterations = (
                request.max_iterations
                if request.max_iterations is not None
                else settings.max_iterations
            )
            initial_hypotheses_count = (
                request.initial_hypotheses_count
                if request.initial_hypotheses_count is not None
                else settings.initial_hypotheses_count
            )
            evolution_max_count = (
                request.evolution_max_count
                if request.evolution_max_count is not None
                else settings.evolution_max_count
            )
            enable_cache = settings.coscientist_cache_enabled
            cache_dir = (
                settings.coscientist_cache_dir
                if settings.coscientist_cache_dir
                else None
            )

            # Log all values being used
            logger.info("Creating HypothesisGenerator (streaming) with parameters:")
            logger.info(f"  model_name: {model_name}")
            logger.info(f"  max_iterations: {max_iterations}")
            logger.info(f"  initial_hypotheses_count: {initial_hypotheses_count}")
            logger.info(f"  evolution_max_count: {evolution_max_count}")
            logger.info(f"  enable_cache: {enable_cache}")
            logger.info(f"  cache_dir: {cache_dir}")

            logger.info(f"Parsed goal details: '{parsed_goal.model_dump_json(indent=2)}'")

            # Create a new generator with overrides
            generator = HypothesisGenerator(
                model_name=model_name,
                max_iterations=max_iterations,
                initial_hypotheses_count=initial_hypotheses_count,
                evolution_max_count=evolution_max_count,
                enable_cache=enable_cache,
                cache_dir=cache_dir,
                tools_config=settings.tools_config,
            )

        # Create cancellation event for this task
        cancelled_event = asyncio.Event()

        # Store the generator coroutine and cancellation event (thread-safe)
        async with _active_tasks_lock:
            _active_tasks[task_id] = {
                "generator": stream_generator(parsed_goal, generator, cancelled_event, task_id),
                "cancelled": cancelled_event,
            }

        logger.info(f"Started generation task {task_id}")
        return {"task_id": task_id, "status": "started"}

    except Exception as e:
        logger.error(f"Error starting generation: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to start generation: {str(e)}"
        )


@app.get("/generate/stream/{task_id}", tags=["hypotheses"])
async def stream_generation(task_id: str):
    """
    Subscribe to Server-Sent Events stream for a started generation task.

    Use the task_id returned from POST /generate/start
    """
    # Check if task exists and get generator (thread-safe)
    async with _active_tasks_lock:
        if task_id not in _active_tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        task_data = _active_tasks[task_id]
        stream = task_data["generator"]

    async def event_stream():
        try:
            async for event in stream:
                yield event
        except Exception as e:
            logger.error(f"Error in stream for task {task_id}: {e}", exc_info=True)
            error_data = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"
        finally:
            # Clean up task when stream completes (thread-safe)
            async with _active_tasks_lock:
                if task_id in _active_tasks:
                    del _active_tasks[task_id]
                    logger.info(f"Cleaned up task {task_id}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class CancelRequest(BaseModel):
    """Request model for cancellation."""
    task_id: str = Field(..., description="The task ID to cancel")


@app.post("/cancel_hypothesis_generation", tags=["hypotheses"])
async def cancel_generation(request: CancelRequest):
    """
    Cancel an ongoing hypothesis generation task.

    This stops the streaming and prevents further processing of the generation workflow.
    Note: LLM calls already in progress will complete, but no new nodes will be processed.
    """
    task_id = request.task_id

    # Check if task exists and get cancellation event (thread-safe)
    async with _active_tasks_lock:
        if task_id not in _active_tasks:
            logger.warning(f"Attempted to cancel non-existent task: {task_id}")
            raise HTTPException(status_code=404, detail="Task not found or already completed")
        task_data = _active_tasks[task_id]
        cancelled_event = task_data["cancelled"]

    try:
        # Set cancellation event - the generator will check this and exit gracefully
        cancelled_event.set()
        logger.info(f"Set cancellation flag for task {task_id}")

        # Note: We don't remove the task from _active_tasks here
        # The streaming endpoint will clean it up when the generator exits
        # This prevents race conditions between cancellation and stream cleanup

        return {
            "status": "cancelled",
            "task_id": task_id,
            "message": "Generation task cancellation requested. The stream will stop after the current node completes."
        }

    except Exception as e:
        logger.error(f"Error cancelling task {task_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel task: {str(e)}"
        )


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )

