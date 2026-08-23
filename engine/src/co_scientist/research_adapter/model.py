"""The five model judgements the research loop needs, over this engine's LLM.

The other half of the adapter (see ``retrieval``). ``ResearchModelPort``
asks for five typed answers; this returns them by way of the house
``call_llm_json``, so JSON repair, schema retries and the budget
escalation ladder stay where every other node already has them rather
than being reimplemented inside the loop.

Two things here are load-bearing rather than incidental. Each call site
sets ``max_tokens`` deliberately -- these are thinking-enabled calls, and
a budget chosen for the answer alone is what lets a chain of thought
consume the whole allowance. And documents reach the extractor numbered,
with the schema naming a document by that number, so the reply's length
tracks how much was *found* rather than how much was read.
"""

from __future__ import annotations

from collections.abc import Sequence

from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    EXTENDED_MAX_TOKENS,
    strip_citation_markers,
    truncate_for_prompt,
)
from co_scientist.llm import call_llm_json
from co_scientist.llm_types import CompletionSpec, LLMCallOptions
from co_scientist.prompts import load_prompt_with_schema
from co_scientist.research import (
    Document,
    ExtractedFinding,
    Extraction,
    Finding,
)

# Per-document character budget for the extraction prompt. Far below the
# whole-paper budget the per-paper analysis uses, because that call embeds
# one paper and this one embeds every document a question admitted -- the
# same ceiling would multiply by the level's breadth. A read that needs
# more than this is a read the loop should have narrowed with a better
# question.
_DOCUMENT_MAX_CHARS = 24_000


class LlmResearchModel:
    """Answer the loop's five questions with one configured model.

    The model is chosen at construction, not per call, so the caller
    decides which of a run's models pays for its research -- the same
    separation the rest of the engine keeps between worker and supervisor
    models.
    """

    def __init__(
        self,
        model_name: str,
        *,
        run_id: str | None = None,
        temperature: float = 0.4,
        use_cache: bool = True,
    ) -> None:
        """Bind the model and the run this research belongs to.

        Args:
            model_name: LiteLLM model name to call.
            run_id: Owning run, for per-run cache scoping and logging.
            temperature: Sampling temperature for all five calls. Lower
                than the generation default: every one of these is a
                reading or rendering task, where variety is noise.
            use_cache: Whether a cached response may satisfy a call.
        """
        self._model = model_name
        self._run_id = run_id
        self._temperature = temperature
        self._use_cache = use_cache

    async def plan_stances(self, *, goal: str, limit: int) -> Sequence[str]:
        """Choose the perspectives the first level should cover."""
        data = await self._ask(
            "research_stances",
            {"research_goal": goal, "limit": limit},
            DEFAULT_MAX_TOKENS,
        )
        return _strings(data.get("stances"))[:limit]

    async def ask_questions(
        self, *, goal: str, stance: str, limit: int
    ) -> Sequence[str]:
        """Ask what one stance needs to know."""
        data = await self._ask(
            "research_questions",
            {"research_goal": goal, "stance": stance, "limit": limit},
            DEFAULT_MAX_TOKENS,
        )
        return _strings(data.get("questions"))[:limit]

    async def to_query(self, *, question: str) -> str:
        """Render a question as a source-shaped query."""
        data = await self._ask(
            "research_query", {"question": question}, DEFAULT_MAX_TOKENS
        )
        query = data.get("query")
        # A model that returns nothing usable has not refused the
        # question, so the question's own text is the honest fallback --
        # a worse query than it could have written, not a dropped thread.
        return query.strip() if isinstance(query, str) and query else question

    async def extract(
        self, *, question: str, documents: Sequence[Document]
    ) -> Extraction:
        """Read the admitted documents for one question."""
        if not documents:
            return Extraction()
        data = await self._ask(
            "research_extract",
            {
                "question": question,
                "documents": _numbered(documents),
            },
            EXTENDED_MAX_TOKENS,
        )
        return Extraction(
            findings=_findings(data.get("findings"), documents),
            follow_ups=tuple(_strings(data.get("follow_ups"))),
        )

    async def compress(
        self, *, question: str, findings: Sequence[Finding]
    ) -> str:
        """Reduce one answered question to an account worth carrying."""
        if not findings:
            return ""
        data = await self._ask(
            "research_compress",
            {
                "question": question,
                "findings": "\n".join(
                    f"- {finding.text} ({finding.locator})"
                    for finding in findings
                ),
            },
            DEFAULT_MAX_TOKENS,
        )
        summary = data.get("summary")
        return summary.strip() if isinstance(summary, str) else ""

    async def _ask(
        self,
        prompt_name: str,
        variables: dict[str, object],
        max_tokens: int,
    ) -> dict[str, object]:
        """Render one prompt with its schema and call the model."""
        prompt, schema = load_prompt_with_schema(prompt_name, variables)
        result = await call_llm_json(
            prompt,
            CompletionSpec(
                model_name=self._model,
                max_tokens=max_tokens,
                temperature=self._temperature,
                json_schema=schema,
            ),
            options=LLMCallOptions(
                use_cache=self._use_cache,
                run_id=self._run_id,
                prompt_name=prompt_name,
            ),
        )
        return result


def _numbered(documents: Sequence[Document]) -> str:
    """Render the documents the way the extraction schema indexes them.

    Strips each document's own inline citation markers from this prompt
    copy (``document.text`` itself is untouched) -- left in, the
    extraction model can copy one into a reported finding as if it were
    its own.
    """
    blocks = []
    for index, document in enumerate(documents):
        kind = "full text" if document.full_text else "abstract only"
        text = strip_citation_markers(
            truncate_for_prompt(document.text, _DOCUMENT_MAX_CHARS)
        )
        blocks.append(f"[{index}] {document.hit.title} ({kind})\n{text}")
    return "\n\n".join(blocks)


def _findings(
    raw: object, documents: Sequence[Document]
) -> tuple[ExtractedFinding, ...]:
    """Bind each reported finding back to the document it was drawn from.

    A finding whose index names no document is dropped rather than
    attributed to a neighbour: the whole value of a finding is which
    source it came from, and a plausible wrong locator is worse than one
    fewer finding.
    """
    if not isinstance(raw, list):
        return ()
    bound = (_one_finding(item, documents) for item in raw)
    return tuple(finding for finding in bound if finding is not None)


def _one_finding(
    item: object, documents: Sequence[Document]
) -> ExtractedFinding | None:
    """Validate one reported finding, or refuse it."""
    if not isinstance(item, dict):
        return None
    index, claim, quote = (
        item.get("document"),
        item.get("claim"),
        item.get("quote"),
    )
    if not isinstance(index, int) or not 0 <= index < len(documents):
        return None
    if not isinstance(claim, str) or not isinstance(quote, str):
        return None
    if not claim.strip() or not quote.strip():
        return None
    return ExtractedFinding(
        text=claim.strip(),
        locator=documents[index].hit.locator,
        span=quote.strip(),
    )


def _strings(raw: object) -> list[str]:
    """Take the non-empty strings out of a model's list, in order."""
    if not isinstance(raw, list):
        return []
    return [
        item.strip() for item in raw if isinstance(item, str) and item.strip()
    ]
