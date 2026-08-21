"""Shared tool fixtures for the deep-research adapter and phase tests.

Both files need the same thing: a registry holding only tools this suite
declares (so nothing depends on the bundled default config or a
developer's home directory), a literature-review workflow with one
enabled search source and one disabled one, and a client that answers
tool calls from a scripted table.
"""

from pathlib import Path
from typing import Any

from co_scientist.config.registry import ToolRegistry
from co_scientist.config.workflow_schema import WorkflowConfig

RESEARCH_TOOLS_CONFIG = """
version: "2.0"
settings:
  merge_strategy: replace
servers:
  s:
    url: "http://example.test/mcp"
    transport: "streamable_http"
    enabled: true
tools:
  search_tools:
    alpha:
      server: "s"
      mcp_tool_name: "search_alpha"
      category: "search"
      enabled: true
    beta:
      server: "s"
      mcp_tool_name: "search_beta"
      category: "search"
      enabled: true
  utility_tools:
    reader:
      server: "s"
      mcp_tool_name: "read_pdf"
      enabled: true
workflows:
  literature_review:
    search_sources:
      - tool: "alpha"
        papers_per_query: 2
        enabled: true
        content_tool: "reader"
        content_url_field: "pdf_url"
      - tool: "beta"
        enabled: false
"""


class FakeResearchClient:
    """Records tool calls and answers them from a scripted table.

    A scripted value that is an ``Exception`` is raised instead of
    returned, so a source that fails and a source that comes back empty
    can both be driven.
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        """Hold the per-tool answers this client will give."""
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Answer one tool call, recording what it was asked."""
        self.calls.append((tool_name, kwargs))
        answer = self.responses.get(tool_name)
        if isinstance(answer, Exception):
            raise answer
        return answer


def research_registry(tmp_path: Path) -> ToolRegistry:
    """Build a registry holding only the tools declared above."""
    path = tmp_path / "tools.yaml"
    path.write_text(RESEARCH_TOOLS_CONFIG)
    return ToolRegistry(config_path=str(path), skip_user_config=True)


def research_workflow(registry: ToolRegistry) -> WorkflowConfig:
    """Take the literature-review workflow off a research registry."""
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    return workflow


_PAPERS = {
    "doc-a": {
        "title": "Blockade in humans",
        "abstract": "TGF-beta blockade reduced fibrosis in a human cohort.",
        "pdf_url": "u/a",
    },
    "doc-b": {"title": "Merely listed", "abstract": "Unrelated."},
}


class _ScriptedModel:
    """Answers each of the five research prompts by what it was asked."""

    def __init__(self) -> None:
        """Start with nothing asked."""
        self.prompts: list[str] = []

    async def __call__(
        self, prompt: str, spec: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        """Answer one prompt, recording it."""
        self.prompts.append(prompt)
        if "perspectives to research" in prompt:
            return {"stances": ["mechanism"]}
        if "questions this perspective needs" in prompt:
            return {"questions": ["is the mechanism shown in humans?"]}
        if "search query" in prompt:
            return {"query": "TGF-beta blockade human"}
        if "retrieved documents" in prompt:
            return {
                "findings": [
                    {
                        "document": 0,
                        "claim": "Blockade reduced fibrosis in humans",
                        "quote": (
                            "TGF-beta blockade reduced fibrosis in a"
                            " human cohort."
                        ),
                    }
                ],
                "follow_ups": [],
            }
        return {"summary": "Human evidence exists but is thin."}
