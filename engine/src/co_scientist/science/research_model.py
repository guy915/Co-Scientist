from __future__ import annotations

from collections.abc import Sequence

from co_scientist.core.constants import (
    DEFAULT_MAX_TOKENS,
    EXTENDED_MAX_TOKENS,
    strip_citation_markers,
    truncate_for_prompt,
)
from co_scientist.platform.llm import CompletionSpec, LLMCallOptions, call_llm_json
from co_scientist.platform.retrieval.research import (
    Document,
    ExtractedFinding,
    Extraction,
    Finding,
    stripped_string_items,
)
from co_scientist.science.prompts import load_prompt_with_schema

# Extraction embeds every admitted document, so a whole-paper limit would
# multiply by breadth.
_DOCUMENT_MAX_CHARS = 24_000


class LlmResearchModel:
    """Bind the model once so callers choose whether worker or supervisor
    budgets fund research.
    """

    def __init__(
        self,
        model_name: str,
        *,
        run_id: str | None = None,
        temperature: float = 0.4,
    ) -> None:
        """Reading and rendering use lower temperature because variety is
        noise.
        """
        self._model = model_name
        self._run_id = run_id
        self._temperature = temperature

    async def plan_stances(self, *, goal: str, limit: int) -> Sequence[str]:
        data = await self._ask(
            "research_stances",
            {"research_goal": goal, "limit": limit},
            DEFAULT_MAX_TOKENS,
        )
        return stripped_string_items(data.get("stances"))[:limit]

    async def ask_questions(self, *, goal: str, stance: str, limit: int) -> Sequence[str]:
        data = await self._ask(
            "research_questions",
            {"research_goal": goal, "stance": stance, "limit": limit},
            DEFAULT_MAX_TOKENS,
        )
        return stripped_string_items(data.get("questions"))[:limit]

    async def to_query(self, *, question: str) -> str:
        data = await self._ask("research_query", {"question": question}, DEFAULT_MAX_TOKENS)
        query = data.get("query")
        # An unusable query is not a refused question; retain the original
        # thread as fallback.
        return query.strip() if isinstance(query, str) and query else question

    async def extract(self, *, question: str, documents: Sequence[Document]) -> Extraction:
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
            follow_ups=tuple(stripped_string_items(data.get("follow_ups"))),
        )

    async def compress(self, *, question: str, findings: Sequence[Finding]) -> str:
        if not findings:
            return ""
        data = await self._ask(
            "research_compress",
            {
                "question": question,
                "findings": "\n".join(
                    f"- {finding.text} ({finding.locator})" for finding in findings
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
        prompt, schema = load_prompt_with_schema(prompt_name, variables)
        result = await call_llm_json(
            prompt,
            CompletionSpec(
                role="research_extract" if prompt_name == "research_extract" else "research",
                model_name=self._model,
                max_tokens=max_tokens,
                temperature=self._temperature,
                json_schema=schema,
            ),
            options=LLMCallOptions(
                run_id=self._run_id,
                prompt_name=prompt_name,
            ),
        )
        return result


def _numbered(documents: Sequence[Document]) -> str:
    """Strip source citation markers only from the prompt copy to prevent
    false finding attribution.
    """
    blocks = []
    for index, document in enumerate(documents):
        kind = "full text" if document.full_text else "abstract only"
        text = strip_citation_markers(truncate_for_prompt(document.text, _DOCUMENT_MAX_CHARS))
        blocks.append(f"[{index}] {document.hit.title} ({kind})\n{text}")
    return "\n\n".join(blocks)


def _findings(raw: object, documents: Sequence[Document]) -> tuple[ExtractedFinding, ...]:
    """Drop unknown document indexes rather than invent plausible source
    provenance.
    """
    if not isinstance(raw, list):
        return ()
    bound = (_one_finding(item, documents) for item in raw)
    return tuple(finding for finding in bound if finding is not None)


def _one_finding(item: object, documents: Sequence[Document]) -> ExtractedFinding | None:
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
