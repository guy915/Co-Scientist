import json
from typing import Any

import pytest

from co_scientist.science.prompts import (
    DebatePromptRequest,
    DraftPromptRequest,
    get_debate_generation_prompt,
    get_draft_prompt_with_tools,
)
from co_scientist.science.prompts.planning import (
    DirectionWritingMaterial,
    get_research_overview_direction_prompt,
)
from tests._state import make_article


def _evidence() -> str:
    return "\n".join(
        f"- evidence-{i}: title=Experiment {i}; source=pubmed; source_id=pmid-{i}; "
        f"abstract={'The assay observes a dose-dependent effect with rescue controls. ' * 48}"
        for i in range(1, 81)
    )


def _request_bytes(prompt: str, schema: dict[str, object] | None) -> int:
    return len((prompt + json.dumps(schema)).encode())


def test_direction_writer_bounds_context_and_retains_grounding_handles() -> None:
    prompt, schema = get_research_overview_direction_prompt(
        "Test causal feedback in metabolic disease",
        DirectionWritingMaterial(
            "Selective rescue", "Discriminate causal feedback", "Selective rescue"
        ),
        "\n".join(
            f"Idea {i}: " + "A supported mechanism with a falsifiable control. " * 50
            for i in range(20)
        ),
        _evidence(),
    )

    assert _request_bytes(prompt, schema) <= 32_000
    assert "evidence-1" in prompt
    assert "pmid-1" in prompt
    assert "Selective rescue" in prompt
    for i in range(20):
        assert f"Idea {i}:" in prompt
    assert schema is not None


@pytest.mark.parametrize("final_turn", [False, True])
def test_generation_debate_sends_bounded_turn_summaries(final_turn: bool) -> None:
    transcript = "".join(
        f"\n\nTurn {i}:\n"
        + f"Objection {i}: causal uncertainty. " * 400
        + f"\nResolution {i}: retain the rescue control."
        for i in range(1, 11)
    )
    prompt, schema = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="Test causal feedback in metabolic disease",
            transcript=transcript,
            articles_with_reasoning=_evidence(),
            reference_list="\n".join(f"[C{i}] Experiment {i}; pmid-{i}" for i in range(1, 81)),
            is_final_turn=final_turn,
        )
    )

    assert _request_bytes(prompt, schema) <= 32_000
    assert "Turn 1" in prompt
    assert "Turn 10" in prompt
    assert "Resolution 10" in prompt
    assert "[C1]" in prompt
    if final_turn:
        assert schema is not None
        assert "literature_grounding" in prompt
        assert "falsification" in prompt.lower()


def test_generation_draft_bounds_repeated_literature_context() -> None:
    prompt, schema = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="Test causal feedback in metabolic disease",
            hypotheses_count=3,
            articles_with_reasoning=_evidence(),
            articles=[
                make_article(title=f"Experiment {i}", used_in_analysis=True) for i in range(80)
            ],
            reference_list="\n".join(f"[C{i}] Experiment {i}; pmid-{i}" for i in range(1, 81)),
            lab_constraints=["Use primary cells; no animal experiments."],
        )
    )

    assert _request_bytes(prompt, schema) <= 32_000
    assert "[C1]" in prompt
    assert "no animal experiments" in prompt
    assert schema is not None


def test_meta_review_summarizes_history_without_losing_votes_or_assessments() -> None:
    from co_scientist.science.prompts.context_budget import summarize_feedback

    records: list[dict[str, Any]] = [
        {
            "record_type": "review_history",
            "hypothesis_index": i,
            "hypothesis_text": f"Mechanism {i}: " + "causal rescue evidence " * 200,
            "elo_rating": 1200 + i,
            "deep_verification_verdict": "unsupported" if i == 2 else "supported",
            "reviews": [
                {"score": 2, "reasoning": "Old uncertain result " * 300},
                {"score": 4, "reasoning": "Latest rescue result " * 300},
            ],
        }
        for i in range(1, 21)
    ]
    records.append(
        {
            "record_type": "ranking_debate",
            "hypothesis_a_id": "idea-1",
            "hypothesis_b_id": "idea-2",
            "winner_id": "idea-1",
            "confidence": 0.8,
            "reasoning": "Rescue distinguishes causality " * 300,
            "debate_transcript": [
                {
                    "turn": i,
                    "winner_id": "idea-1",
                    "presentation_order": order,
                    "valid_output": True,
                    "decision_summary": "Rescue supports causality " * 300,
                }
                for i, order in enumerate(("ab", "ba", "ab"), 1)
            ],
        }
    )
    serialized = json.dumps(records)
    summarized = summarize_feedback(serialized)
    tables = json.loads(summarized)
    parsed = [
        dict(zip(table["columns"], row, strict=True))
        for table in tables.values()
        if "rows" in table
        for row in table["rows"]
    ]

    assert len(summarized) <= 18_000
    assert [record["hypothesis_index"] for record in parsed[:-1]] == list(range(1, 21))
    assert parsed[1]["deep_verification_verdict"] == "unsupported"
    assert parsed[0]["latest_score"] == 4
    assert parsed[0]["review_count"] == 2
    assert parsed[-1]["debate_transcript"]["presentation_order"] == [
        "ab",
        "ba",
        "ab",
    ]
    assert parsed[-1]["winner_id"] == "idea-1"
    assert records[0]["reviews"][0]["score"] == 2


def test_overview_summary_keeps_every_numbered_idea_and_elo() -> None:
    from co_scientist.science.prompts.context_budget import summarize_hypotheses

    summary = "\n".join(
        f"{i}. (Elo {1200 + i}) " + f"Mechanism {i} with controls. " * 200 for i in range(1, 11)
    )
    result = summarize_hypotheses(summary)

    assert len(result) <= 6_000
    for i in range(1, 11):
        assert f"{i}. (Elo {1200 + i})" in result
    assert "omitted text is not evidence of absence" in result


def test_evolution_bounds_evidence_but_keeps_every_reference_key() -> None:
    from co_scientist.science.citations import ReferenceIndex
    from co_scientist.science.evolution import EvolutionContext
    from co_scientist.science.evolution.evolve_prompt import (
        _build_evolution_prompt,
        _EvolutionOperation,
    )
    from tests._state import make_hypothesis, make_state

    references = "\n".join(
        f"[C{i}] Author et al., 2023 - " + f"Mechanism {i} with rescue controls. " * 60
        for i in range(1, 129)
    )
    index = ReferenceIndex(text=references, sources={})
    prompt, schema = _build_evolution_prompt(
        make_hypothesis(text="Retain the causal rescue control."),
        [],
        EvolutionContext(
            model_name="test-model",
            meta_review={},
            removed_duplicates=[],
            state=make_state(),
            articles_with_reasoning=_evidence(),
            reference_index=index,
        ),
        _EvolutionOperation(),
        grounding_evidence=_evidence(),
    )

    assert _request_bytes(prompt, schema) <= 32_000
    for i in range(1, 129):
        assert f"[C{i}]" in prompt
    assert "Retain the causal rescue control." in prompt
    assert "evidence-1" in prompt
    assert index.text == references
    assert schema is not None
