# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""FastAPI application main module."""

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from rich.console import Console

# Load .env file before importing settings
load_dotenv()

from app import engine_adapter  # pylint: disable=wrong-import-position
from app.config import settings  # pylint: disable=wrong-import-position
from app.runs import router as runs_router  # pylint: disable=wrong-import-position
from app.seed import seed_demo_runs  # pylint: disable=wrong-import-position

try:
    from litellm import acompletion
except Exception:  # pragma: no cover - litellm optional in mock mode  # pylint: disable=broad-exception-caught
    acompletion = None

try:
    from co_scientist import HypothesisGenerator  # type: ignore[import-not-found, unused-ignore]
except Exception:  # pragma: no cover - engine optional in mock mode  # pylint: disable=broad-exception-caught
    HypothesisGenerator = None  # pylint: disable=invalid-name

# Configure logging
# Set root logger to INFO to suppress DEBUG logs from dependencies (httpx, etc.)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Set application loggers (viewer and co_scientist) to DEBUG if debug mode is enabled  # pylint: disable=line-too-long
logger = logging.getLogger(__name__)
coscientist_logger = logging.getLogger("co_scientist")
if settings.debug:
    logger.setLevel(logging.DEBUG)
    coscientist_logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)
    coscientist_logger.setLevel(logging.INFO)
console = Console()

# Set environment variables for the LLM engine
# LiteLLM uses provider-specific env vars (GEMINI_API_KEY, OPENAI_API_KEY, etc.)
if settings.gemini_api_key:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
if settings.coscientist_cache_enabled:
    os.environ["COSCIENTIST_CACHE_ENABLED"] = "true"
if settings.coscientist_cache_dir:
    os.environ["COSCIENTIST_CACHE_DIR"] = settings.coscientist_cache_dir
if settings.coscientist_lit_review_papers_count:
    os.environ["COSCIENTIST_LIT_REVIEW_PAPERS_COUNT"] = str(
        settings.coscientist_lit_review_papers_count)

# Set MCP server URL if available
if settings.mcp_server_url:
    os.environ["MCP_SERVER_URL"] = settings.mcp_server_url
    logger.info("mcp_server_url configured: %s", settings.mcp_server_url)
else:
    logger.info("mcp_server_url not set - literature review will be disabled")

# Global generator instance (can be reused)
_generator = None

# Active generation tasks
# task_id -> {"generator": AsyncGenerator, "cancelled": asyncio.Event}
# Protected by lock for thread-safe concurrent access
_active_tasks: dict[str, dict[str, Any]] = {}
_active_tasks_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(
    app: FastAPI,  # pylint: disable=redefined-outer-name,unused-argument
) -> AsyncGenerator[None, None]:
    """Manages FastAPI application startup and shutdown."""
    global _generator

    # Startup
    logger.info("Starting Co-Scientist server...")
    logger.info("Model: %s", settings.model_name)
    logger.info("Max iterations: %s", settings.max_iterations)
    logger.info("Initial hypotheses count: %s",
                settings.initial_hypotheses_count)
    logger.info("Evolution max count: %s", settings.evolution_max_count)
    if settings.tools_config:
        logger.info("Tools config: %s", settings.tools_config)
    else:
        logger.info("Tools config: not set (generator defaults)")

    provider = engine_adapter.select_provider()
    logger.info("Workflow provider: %s", provider)

    if HypothesisGenerator is not None and provider == "engine":
        _generator = HypothesisGenerator(
            model_name=settings.model_name,
            supervisor_model_name=settings.supervisor_model_name,
            max_iterations=settings.max_iterations,
            initial_hypotheses_count=settings.initial_hypotheses_count,
            evolution_max_count=settings.evolution_max_count,
            enable_cache=settings.coscientist_cache_enabled,
            cache_dir=settings.coscientist_cache_dir
            if settings.coscientist_cache_dir else None,
            tools_config=settings.tools_config,
        )
    else:
        logger.info(
            "Engine generator not initialised; mock workflow will be used.")
        _generator = None

    await seed_demo_runs(db_path=os.getenv("COSCIENTIST_DB_PATH") or None)

    yield

    # Shutdown
    logger.info("Shutting down Co-Scientist server...")


app = FastAPI(
    title="Co-Scientist API",
    description="FastAPI server for AI hypothesis generation",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins = ([
    o.strip() for o in _allowed_origins_env.split(",") if o.strip()
] if _allowed_origins_env else ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the new run-lifecycle router (durable, persisted, SSE).
app.include_router(runs_router)


# Request/Response models
class GenerateRequest(BaseModel):
    """Request model for hypothesis generation."""

    research_goal: str = Field(..., description="The research question or goal")
    model_name: str | None = Field(
        None, description="Override default model name (optional)")
    max_iterations: int | None = Field(
        None, description="Override default max iterations (optional)")
    initial_hypotheses_count: int | None = Field(
        None,
        description="Override default initial hypotheses count (optional)")
    evolution_max_count: int | None = Field(
        None, description="Override default evolution max count (optional)")
    supervisor_model_name: str | None = Field(
        None, description="Override supervisor/meta-review model (optional)")
    enable_literature_review_node: bool | None = Field(
        None,
        description=
        "Whether to include literature review node (default: auto-detect based on mcp server availability)",  # pylint: disable=line-too-long
    )


class GenerateResponse(BaseModel):
    """Response model for hypothesis generation (non streaming)."""
    hypotheses: list[dict[str, Any]]
    meta_review: dict[str, Any]
    research_plan: dict[str, Any]
    tournament_matchups: list[dict[str, Any]]
    evolution_details: list[dict[str, Any]]
    execution_time: float
    metrics: dict[str, Any]


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

    mcp_available: bool = Field(...,
                                description="whether mcp server is available")
    pubmed_available: bool = Field(
        ..., description="whether pubmed api is available")
    literature_review_available: bool = Field(
        ...,
        description=
        "whether literature review is available (requires both mcp and pubmed)")
    mcp_server_url: str = Field(..., description="configured mcp server url")
    provider: str = Field(
        "mock", description="active workflow provider: 'mock' | 'engine'")
    mock_mode: bool = Field(
        False, description="true when running deterministic mock workflow")
    has_provider_key: bool = Field(False,
                                   description="any LLM provider key is set")
    engine_importable: bool = Field(
        False, description="co_scientist package is importable")
    model_name: str = Field("", description="configured model id")


class ParsedResearchGoal(BaseModel):
    """Parsed structure from user input."""

    research_goal: str = Field(...,
                               description="The core research question or goal")
    preferences: str | None = Field(None,
                                    description="Desired approach or focus")
    attributes: list[str] | None = Field(
        None, description="Key qualities to prioritize")
    constraints: list[str] | None = Field(
        None, description="Requirements or boundaries")
    user_inputs: dict[str, Any] | None = Field(
        None, description="Additional user-provided context")
    enable_literature_review_node: bool | None = Field(
        None,
        description=
        "Whether to include literature review node (optional, auto-detect if not specified)"  # pylint: disable=line-too-long
    )


def _get_parse_cache_dir() -> Path:
    """Get the viewer parse cache directory."""
    cache_dir = os.getenv("COSCIENTIST_CACHE_DIR", ".coscientist_cache")
    parse_cache_dir = Path(cache_dir) / "viewer-cache"
    parse_cache_dir.mkdir(parents=True, exist_ok=True)
    return parse_cache_dir


def _get_cached_parse(raw_input: str) -> ParsedResearchGoal | None:
    """Get cached parsed research goal if available."""
    try:
        cache_dir = _get_parse_cache_dir()
        cache_key = hashlib.md5(raw_input.encode()).hexdigest()
        cache_file = cache_dir / f"{cache_key}.json"

        if cache_file.exists():
            with open(cache_file, encoding="utf-8") as f:
                cached_data = json.load(f)
            logger.info("parse cache hit for input: %s...", raw_input[:50])
            return ParsedResearchGoal(**cached_data)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("failed to read parse cache: %s", e)

    return None


def _cache_parse(raw_input: str, parsed: ParsedResearchGoal) -> None:
    """Cache parsed research goal to disk."""
    try:
        cache_dir = _get_parse_cache_dir()
        cache_key = hashlib.md5(raw_input.encode()).hexdigest()
        cache_file = cache_dir / f"{cache_key}.json"

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(parsed.model_dump(), f, indent=2)

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to cache parse: %s", e)


async def parse_research_goal_input(raw_input: str) -> ParsedResearchGoal:
    """Parse broad research goal input using LLM with JSON schema."""

    # Check cache first
    cached = _get_cached_parse(raw_input)
    if cached is not None:
        return cached

    # pylint: disable=line-too-long
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
    # pylint: enable=line-too-long

    response_schema = {
        "type": "object",
        "properties": {
            "research_goal": {
                "type": "string",
                "description": "The core research question or goal"
            },
            "preferences": {
                "type":
                    "string",
                "description":
                    "Desired approach or focus (empty string if not present)"
            },
            "attributes": {
                "type":
                    "array",
                "items": {
                    "type": "string"
                },
                "description":
                    "Key qualities to prioritize (empty array if not present)"
            },
            "constraints": {
                "type":
                    "array",
                "items": {
                    "type": "string"
                },
                "description":
                    "Requirements or boundaries (empty array if not present)"
            },
            "user_inputs": {
                "type": "object",
                "properties": {
                    "starting_hypotheses": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    },
                    "literature": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    }
                },
                "description": "Additional user-provided context"
            }
        },
        "required": ["research_goal"]
    }

    try:
        response = await acompletion(model=settings.model_name,
                                     messages=[{
                                         "role": "user",
                                         "content": prompt
                                     }],
                                     response_format={
                                         "type": "json_schema",
                                         "json_schema": {
                                             "name": "research_goal_parser",
                                             "schema": response_schema
                                         }
                                     })

        parsed_json = json.loads(response.choices[0].message.content)

        # Convert empty strings/arrays to None for optional fields
        if "preferences" in parsed_json and not parsed_json["preferences"]:
            parsed_json["preferences"] = None
        if "attributes" in parsed_json and not parsed_json["attributes"]:
            parsed_json["attributes"] = None
        if "constraints" in parsed_json and not parsed_json["constraints"]:
            parsed_json["constraints"] = None
        if "user_inputs" in parsed_json and not parsed_json["user_inputs"]:
            parsed_json["user_inputs"] = None

        logger.info("Parsed research goal: %s", parsed_json)
        parsed_goal = ParsedResearchGoal(**parsed_json)

        # Cache the result
        _cache_parse(raw_input, parsed_goal)

        return parsed_goal

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error parsing research goal with LLM: %s",
                     e,
                     exc_info=True)
        # Fallback: treat entire input as research_goal
        logger.warning("Falling back to using entire input as research_goal")
        fallback_goal = ParsedResearchGoal(
            research_goal=raw_input,
            preferences=None,
            attributes=None,
            constraints=None,
            user_inputs=None,
            enable_literature_review_node=None,
        )

        # Cache the fallback too
        _cache_parse(raw_input, fallback_goal)

        return fallback_goal


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "message": "Co-Scientist API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        model_name=settings.model_name,
    )


@app.get("/config", response_model=ConfigResponse, tags=["config"])
async def get_config() -> ConfigResponse:
    """Get default configuration values."""
    return ConfigResponse(
        max_iterations=settings.max_iterations,
        initial_hypotheses_count=settings.initial_hypotheses_count,
        evolution_max_count=settings.evolution_max_count,
    )


@app.get("/status", response_model=SystemStatusResponse, tags=["system"])
async def get_system_status() -> dict[str, Any]:
    """Checks system availability for literature review features.

    Returns availability status for mcp server and pubmed api, plus
    provider/mock-mode info from the engine adapter so the UI can render
    a "Mock Mode" banner.
    """
    mcp_available = False
    pubmed_available = False
    try:
        from co_scientist.mcp_client import (  # type: ignore[import-not-found, unused-ignore]  # pylint: disable=import-outside-toplevel
            check_mcp_available, check_pubmed_available_via_mcp,
        )

        mcp_available = await check_mcp_available()
        pubmed_available = await check_pubmed_available_via_mcp()
    except Exception:  # pragma: no cover - engine optional in mock mode  # pylint: disable=broad-exception-caught
        mcp_available = False
        pubmed_available = False

    adapter_status = engine_adapter.system_status()

    return {
        "mcp_available": mcp_available,
        "pubmed_available": pubmed_available,
        "literature_review_available": mcp_available,
        "mcp_server_url": settings.mcp_server_url,
        **adapter_status,
    }


@app.post("/generate", response_model=GenerateResponse, tags=["hypotheses"])
async def generate_hypotheses(request: GenerateRequest) -> GenerateResponse:
    """Generates hypotheses for a research goal.

    Runs the full hypothesis generation workflow and returns the complete
    results when finished.
    """
    if _generator is None:
        raise HTTPException(status_code=503, detail="Generator not initialized")

    try:
        # Use request overrides or fall back to settings/defaults
        generator = _generator
        if any([
                request.model_name,
                request.supervisor_model_name,
                request.max_iterations is not None,
                request.initial_hypotheses_count is not None,
                request.evolution_max_count is not None,
        ]):
            # Capture values with default fallbacks
            model_name = request.model_name or settings.model_name
            supervisor_model_name = request.supervisor_model_name or settings.supervisor_model_name
            max_iterations = (request.max_iterations if request.max_iterations
                              is not None else settings.max_iterations)
            initial_hypotheses_count = (request.initial_hypotheses_count
                                        if request.initial_hypotheses_count
                                        is not None else
                                        settings.initial_hypotheses_count)
            evolution_max_count = (request.evolution_max_count
                                   if request.evolution_max_count is not None
                                   else settings.evolution_max_count)
            enable_cache = settings.coscientist_cache_enabled
            cache_dir = (settings.coscientist_cache_dir
                         if settings.coscientist_cache_dir else None)

            # Log all values being used
            logger.info(
                "Creating HypothesisGenerator (no streaming) with parameters:")
            logger.info("  model_name: %s", model_name)
            logger.info("  supervisor_model_name: %s", supervisor_model_name or
                        model_name)
            logger.info("  max_iterations: %s", max_iterations)
            logger.info("  initial_hypotheses_count: %s",
                        initial_hypotheses_count)
            logger.info("  evolution_max_count: %s", evolution_max_count)
            logger.info("  enable_cache: %s", enable_cache)
            logger.info("  cache_dir: %s", cache_dir)

            # Create a new generator with overrides
            generator = HypothesisGenerator(
                model_name=model_name,
                supervisor_model_name=supervisor_model_name,
                max_iterations=max_iterations,
                initial_hypotheses_count=initial_hypotheses_count,
                evolution_max_count=evolution_max_count,
                enable_cache=enable_cache,
                cache_dir=cache_dir,
                tools_config=settings.tools_config,
            )

        # Generate run_id for non-streaming endpoint
        import uuid  # pylint: disable=import-outside-toplevel
        run_id = str(uuid.uuid4())

        # Prepare opts with enable_literature_review_node if specified
        opts = {}
        if request.enable_literature_review_node is not None:
            opts[
                "enable_literature_review_node"] = request.enable_literature_review_node

        result = await generator.generate_hypotheses(
            research_goal=request.research_goal,
            opts=opts if opts else None,
            run_id=run_id)

        return GenerateResponse(**result)

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error generating hypotheses: %s", e, exc_info=True)
        raise HTTPException(status_code=500,
                            detail=f"Generation failed: {str(e)}") from e


async def stream_generator(
    parsed_goal: ParsedResearchGoal,
    generator: HypothesisGenerator,
    cancelled_event: asyncio.Event,
    task_id: str,
) -> AsyncGenerator[str, None]:
    """Generate Server-Sent Events stream from hypothesis generation."""
    try:
        console.print(
            "\n[bold yellow]═══ sse stream starting ═══[/bold yellow]")
        console.print(
            f"[cyan]research goal:[/cyan] {parsed_goal.research_goal[:100]}...")

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
        console.print(
            "[green]→ Sending sse event:[/green] [dim]type=start[/dim]")
        yield f"data: {json.dumps(start_event)}\n\n"

        # Track iteration for UI grouping
        # The library's current_iteration doesn't increment until AFTER proximity
        # But UI needs to group meta_review/evolve/etc under the next iteration
        has_seen_meta_review = False
        ui_iteration = 0  # For UI display (0 = initial, 1+ = iterations)

        # Pass all parsed fields to the generator
        opts = {
            "preferences": parsed_goal.preferences,
            "attributes": parsed_goal.attributes,
            "constraints": parsed_goal.constraints,
            "user_inputs": parsed_goal.user_inputs,
            "enable_tool_calling_generation": True,
        }

        # Add enable_literature_review_node if specified
        if parsed_goal.enable_literature_review_node is not None:
            opts[
                "enable_literature_review_node"] = parsed_goal.enable_literature_review_node

        async for node_name, state in generator.generate_hypotheses(
                research_goal=parsed_goal.research_goal,
                opts=opts,
                run_id=task_id,
                stream=True):
            # Check if cancelled before processing each node
            if cancelled_event.is_set():
                console.print("[red]✗ generation cancelled by user[/red]")
                logger.info("generation cancelled by user")
                yield "data: {\"type\": \"cancelled\", \"message\": \"generation cancelled\"}\n\n"  # pylint: disable=line-too-long
                return

            # Format as Server-Sent Event

            # Determine UI iteration based on workflow phase
            # Initial generation (iteration 0): supervisor → literature_review → generate → reflection → review → ranking  # pylint: disable=line-too-long
            # Evolution iterations (1+): meta_review → evolve → review → ranking → proximity

            if node_name == "meta_review":
                # Entering an evolution iteration
                has_seen_meta_review = True
                ui_iteration = state.get("current_iteration", 0) + 1
            elif not has_seen_meta_review:
                # Still in initial generation
                ui_iteration = 0
            # Else: keep current ui_iteration (we're in an evolution cycle)

            # Add iteration info to state
            state["ui_iteration"] = ui_iteration
            state[
                "iteration_phase"] = "initial" if ui_iteration == 0 else f"iteration_{ui_iteration}"  # pylint: disable=line-too-long

            event_data = {
                "type": "update",
                "node": node_name,
                "state": state,
            }

            console.print(
                f"[green]→ Sending sse event:[/green] [cyan]type=update, node={node_name}[/cyan]"  # pylint: disable=line-too-long
            )

            yield f"data: {json.dumps(event_data)}\n\n"

            # Small delay to prevent overwhelming the client
            await asyncio.sleep(0.1)

        # Check if cancelled before sending completion
        if cancelled_event.is_set():
            console.print("[red]Generation cancelled by user[/red]")
            yield "data: {\"type\": \"cancelled\", \"message\": \"generation cancelled\"}\n\n"  # pylint: disable=line-too-long
            return

        # Send completion event
        console.print(
            "[bold green]Sending sse event: type=complete[/bold green]")
        yield "data: {\"type\": \"complete\", \"message\": \"hypothesis generation completed\"}\n\n"  # pylint: disable=line-too-long

    except asyncio.CancelledError:
        console.print("[red]Generation cancelled (CancelledError)[/red]")
        yield "data: {\"type\": \"cancelled\", \"message\": \"generation cancelled\"}\n\n"  # pylint: disable=line-too-long
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("error in streaming: %s", e, exc_info=True)
        error_data = {"type": "error", "message": str(e)}
        yield f"data: {json.dumps(error_data)}\n\n"


@app.post("/generate/start", tags=["hypotheses"])
async def start_generation(request: GenerateRequest) -> dict[str, str]:
    """Starts hypothesis generation and returns a task ID.

    Use the returned task_id to subscribe to the SSE stream via
    GET /generate/stream/{task_id}.
    """
    if _generator is None:
        raise HTTPException(status_code=503, detail="Generator not initialized")

    try:
        import uuid  # pylint: disable=import-outside-toplevel
        task_id = str(uuid.uuid4())

        # Parse the research goal input to extract structured information
        logger.info("parsing research goal input for task %s", task_id)
        parsed_goal = await parse_research_goal_input(request.research_goal)

        # Override with explicit enable_literature_review_node from request if provided
        if request.enable_literature_review_node is not None:
            parsed_goal.enable_literature_review_node = request.enable_literature_review_node

        logger.info("parsed goal - core: '%s...'",
                    parsed_goal.research_goal[:100])
        if parsed_goal.preferences:
            logger.info("  preferences: %s", parsed_goal.preferences)
        if parsed_goal.attributes:
            logger.info("  attributes: %s", parsed_goal.attributes)
        if parsed_goal.constraints:
            logger.info("  constraints: %s", parsed_goal.constraints)
        if parsed_goal.user_inputs:
            logger.info("  user inputs: %s", parsed_goal.user_inputs)
        if parsed_goal.enable_literature_review_node is not None:
            logger.info("  enable_literature_review_node: %s",
                        parsed_goal.enable_literature_review_node)

        # Use request overrides or fall back to settings/defaults
        generator = _generator
        if any([
                request.model_name,
                request.supervisor_model_name,
                request.max_iterations is not None,
                request.initial_hypotheses_count is not None,
                request.evolution_max_count is not None,
        ]):
            # Capture values with default fallbacks
            model_name = request.model_name or settings.model_name
            supervisor_model_name = request.supervisor_model_name or settings.supervisor_model_name
            max_iterations = (request.max_iterations if request.max_iterations
                              is not None else settings.max_iterations)
            initial_hypotheses_count = (request.initial_hypotheses_count
                                        if request.initial_hypotheses_count
                                        is not None else
                                        settings.initial_hypotheses_count)
            evolution_max_count = (request.evolution_max_count
                                   if request.evolution_max_count is not None
                                   else settings.evolution_max_count)
            enable_cache = settings.coscientist_cache_enabled
            cache_dir = (settings.coscientist_cache_dir
                         if settings.coscientist_cache_dir else None)

            # Log all values being used
            logger.info(
                "Creating HypothesisGenerator (streaming) with parameters:")
            logger.info("  model_name: %s", model_name)
            logger.info("  supervisor_model_name: %s", supervisor_model_name or
                        model_name)
            logger.info("  max_iterations: %s", max_iterations)
            logger.info("  initial_hypotheses_count: %s",
                        initial_hypotheses_count)
            logger.info("  evolution_max_count: %s", evolution_max_count)
            logger.info("  enable_cache: %s", enable_cache)
            logger.info("  cache_dir: %s", cache_dir)

            logger.info("Parsed goal details: '%s'",
                        parsed_goal.model_dump_json(indent=2))

            # Create a new generator with overrides
            generator = HypothesisGenerator(
                model_name=model_name,
                supervisor_model_name=supervisor_model_name,
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
                "generator":
                    stream_generator(parsed_goal, generator, cancelled_event,
                                     task_id),
                "cancelled":
                    cancelled_event,
            }

        logger.info("Started generation task %s", task_id)
        return {"task_id": task_id, "status": "started"}

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error starting generation: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start generation: {str(e)}") from e


@app.get("/generate/stream/{task_id}", tags=["hypotheses"])
async def stream_generation(task_id: str) -> StreamingResponse:
    """Subscribes to the SSE stream for a started generation task.

    Use the task_id returned from POST /generate/start.
    """
    # Check if task exists and get generator (thread-safe)
    async with _active_tasks_lock:
        if task_id not in _active_tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        task_data = _active_tasks[task_id]
        stream = task_data["generator"]

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async for event in stream:
                yield event
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error in stream for task %s: %s",
                         task_id,
                         e,
                         exc_info=True)
            error_data = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"
        finally:
            # Clean up task when stream completes (thread-safe)
            async with _active_tasks_lock:
                if task_id in _active_tasks:
                    del _active_tasks[task_id]
                    logger.info("Cleaned up task %s", task_id)

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
async def cancel_generation(request: CancelRequest) -> dict[str, str]:
    """Cancels an ongoing hypothesis generation task.

    Stops the streaming and prevents further processing. LLM calls already in
    progress will complete, but no new nodes will be processed.
    """
    task_id = request.task_id

    # Check if task exists and get cancellation event (thread-safe)
    async with _active_tasks_lock:
        if task_id not in _active_tasks:
            logger.warning("Attempted to cancel non-existent task: %s", task_id)
            raise HTTPException(status_code=404,
                                detail="Task not found or already completed")
        task_data = _active_tasks[task_id]
        cancelled_event = task_data["cancelled"]

    try:
        # Set cancellation event - the generator will check this and exit gracefully
        cancelled_event.set()
        logger.info("Set cancellation flag for task %s", task_id)

        # Note: We don't remove the task from _active_tasks here
        # The streaming endpoint will clean it up when the generator exits
        # This prevents race conditions between cancellation and stream cleanup

        return {
            "status":
                "cancelled",
            "task_id":
                task_id,
            "message":
                "Generation task cancellation requested. The stream will stop after the current node completes."  # pylint: disable=line-too-long
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error cancelling task %s: %s", task_id, e, exc_info=True)
        raise HTTPException(status_code=500,
                            detail=f"Failed to cancel task: {str(e)}") from e


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
