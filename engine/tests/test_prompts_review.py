from __future__ import annotations

from typing import Any

from co_scientist.prompts import (
    PromptRunContext,
    SupervisorPromptInputs,
    get_review_prompt,
    get_supervisor_prompt,
)

_GUIDANCE: dict[str, Any] = {
    "research_goal_analysis": {
        "key_areas": ["mitochondrial dysfunction", "oxidative stress"],
    },
    "workflow_plan": {
        "generation_phase": {
            "focus_areas": ["metabolic pathways"],
            "diversity_targets": "broad",
            "quantity_target": 5,
        },
        "review_phase": {
            "critical_criteria": ["novelty", "testability"],
            "review_depth": "deep",
        },
        "evolution_phase": {
            "refinement_priorities": ["specificity"],
            "iteration_strategy": "incremental",
        },
    },
}


def test_prompt_builders_include_run_setup_guidance() -> None:
    setup_guidance = "Run setup:\n- Requirements:\n  - Focus on primary data"
    focus_guidance = "Prefer novelty while preserving testability."
    prompt, _ = get_supervisor_prompt(
        SupervisorPromptInputs(research_goal="g", criteria=["Causal clarity"]),
        PromptRunContext(
            run_setup_guidance=setup_guidance,
            run_focus_guidance=focus_guidance,
        ),
    )
    assert "Run Setup Guidance" in prompt
    assert "Run Focus Guidance" in prompt
    assert "Focus on primary data" in prompt
    assert "Prefer novelty" in prompt
    assert "Causal clarity" in prompt


def test_review_prompt_critical_criteria_caps_count_and_questions() -> None:
    """The json_object downgrade does not enforce maxItems server-side."""
    guidance = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    {
                        "name": f"criterion {i}",
                        "questions": [
                            {"name": f"q{i}-{j}", "question": f"text {i}-{j}?"}
                            for j in range(6)
                        ],
                    }
                    for i in range(8)
                ]
            }
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "criterion 5" in prompt
    assert "criterion 6" not in prompt
    assert "text 0-3?" in prompt
    assert "text 0-4?" not in prompt


def test_review_prompt_critical_criteria_malformed_entries_degrade() -> None:
    guidance = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    {"name": "Valid Criterion", "questions": ["plain text q"]},
                    {"name": ""},
                    {"questions": []},
                    42,
                    None,
                ],
            }
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "Valid Criterion" in prompt
    assert "plain text q" in prompt


def _enum_values(node: Any, path: str = "") -> list[tuple[str, list[Any]]]:
    if not isinstance(node, dict):
        return []
    found: list[tuple[str, list[Any]]] = []
    if "enum" in node:
        found.append((path or "<root>", node["enum"]))
    for name, subschema in (node.get("properties") or {}).items():
        found += _enum_values(subschema, f"{path}.{name}" if path else name)
    if "items" in node:
        found += _enum_values(node["items"], path + "[]")
    return found
