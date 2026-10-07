import dataclasses
import hashlib
import itertools
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from co_scientist.platform.llm.decisions import Question


@dataclass(frozen=True)
class DecisionCase:
    identifier: str
    prompt: str
    schema: dict[str, Any]
    questions: dict[str, Question]
    reverse_prompt: str | None = None
    side_ids: tuple[str, str] | None = None
    context_basis: str = "recorded text"
    group_id: str | None = None


def _identifier(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _checkpoint_sides(conn: sqlite3.Connection, run_id: str) -> dict[str, dict[str, Any]]:
    from co_scientist.domains.research_state.models import Hypothesis
    from co_scientist.science.ranking.ranking_debate import _ranking_side

    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoints'").fetchone():
        return {}
    sides: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        "SELECT state_json FROM checkpoints WHERE run_id=? ORDER BY seq DESC LIMIT 300", (run_id,)
    ):
        state = json.loads(row["state_json"]).get("state", {})
        for hyp in state.get("hypotheses", []):
            text = hyp.get("text")
            if not isinstance(text, str) or not text.strip() or text in sides:
                continue
            # Never copy a checkpoint's credentials, owner identifiers or runtime settings.
            selected = {
                key: hyp[key]
                for key in (
                    "text",
                    "reviews",
                    "reflection_notes",
                    "deep_verification_probes",
                    "deep_verification_verdict",
                    "enrichments",
                )
                if key in hyp
            }
            sides[text] = dataclasses.asdict(_ranking_side(Hypothesis.from_dict(selected)))
    return sides


def read_corpus(directory: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hypotheses: dict[str, dict[str, Any]] = {}
    papers: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.rglob("*.db")):
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute("SELECT id,research_goal,llm_backend FROM runs"):
                if row["llm_backend"] != "real":
                    continue
                goal = str(row["research_goal"])
                sides = _checkpoint_sides(conn, row["id"])
                for hyp in conn.execute("SELECT * FROM hypotheses WHERE run_id=?", (row["id"],)):
                    text = str(hyp["statement"] or "")
                    if text.strip():
                        hypotheses[_identifier(goal + text)] = {
                            "goal": goal,
                            "text": text,
                            "side": sides.get(text),
                        }
                for paper in conn.execute(
                    "SELECT title,abstract FROM evidence WHERE run_id=?", (row["id"],)
                ):
                    if paper["abstract"]:
                        entry = {
                            "goal": goal,
                            "title": paper["title"],
                            "abstract": paper["abstract"],
                        }
                        papers[_identifier(json.dumps(entry, sort_keys=True))] = entry
    return list(hypotheses.values()), list(papers.values())


def _ranking_cases(hypotheses: list[dict[str, Any]]) -> list[DecisionCase]:
    from co_scientist.science.prompts.ranking import RankingSide, get_ranking_prompt

    cases = []
    question = Question(
        "choice",
        "Which hypothesis best meets the scientific criteria in the state?",
        {"A": "Hypothesis 1", "B": "Hypothesis 2"},
    )
    for a, b in itertools.combinations(hypotheses, 2):
        if a["goal"] != b["goal"]:
            continue
        side_a = RankingSide(**a["side"]) if a.get("side") else RankingSide(a["text"])
        side_b = RankingSide(**b["side"]) if b.get("side") else RankingSide(b["text"])
        prompt, schema = get_ranking_prompt(a["goal"], side_a, side_b)
        reverse, _ = get_ranking_prompt(a["goal"], side_b, side_a)
        assert schema is not None
        cases.append(
            DecisionCase(
                _identifier(prompt),
                prompt,
                schema,
                {"winner": question},
                reverse,
                (_identifier(a["text"]), _identifier(b["text"])),
                "recorded checkpoint reviews"
                if side_a.review and side_b.review
                else "recorded text",
                _identifier(a["goal"]),
            )
        )
    return cases


def _relevance_cases(papers: list[dict[str, Any]]) -> list[DecisionCase]:
    from co_scientist.science.prompts.literature import get_literature_review_relevance_batch_prompt
    from co_scientist.science.schemas import LITERATURE_RELEVANCE_BATCH_SCHEMA

    cases = []
    for paper in papers:
        # The production scorer has the same per-paper abstract character boundary.
        block = f"**Candidate 1:**\nTitle: {paper['title']}\nAbstract: {paper['abstract'][:1500]}"
        prompt = get_literature_review_relevance_batch_prompt(paper["goal"], block)
        question = Question(
            "score",
            "How relevant is Candidate 1 to the research goal?",
            (
                "Unrelated",
                "Slightly related",
                "Partially relevant",
                "Strongly relevant",
                "Directly on point",
            ),
        )
        cases.append(
            DecisionCase(
                _identifier(prompt),
                prompt,
                LITERATURE_RELEVANCE_BATCH_SCHEMA,
                {"relevance": question},
            )
        )
    return cases


def _proximity_cases(hypotheses: list[dict[str, Any]]) -> list[DecisionCase]:
    from co_scientist.science.prompts.ranking import get_proximity_prompt

    question = Question(
        "choice",
        "How similar are hypotheses at indices 0 and 1?",
        {
            "high": "Same mechanism, assumptions, methods and application; safe to deduplicate",
            "medium": "Related theme but different mechanism, assumptions, methods or application",
            "low": "Different research directions",
        },
    )
    cases = []
    for a, b in itertools.combinations(hypotheses, 2):
        if a["goal"] != b["goal"]:
            continue
        prompt, schema = get_proximity_prompt([a["text"], b["text"]])
        assert schema is not None
        cases.append(DecisionCase(_identifier(prompt), prompt, schema, {"similarity": question}))
    return cases


def _safety_cases(hypotheses: list[dict[str, Any]]) -> list[DecisionCase]:
    from co_scientist.domains.safety.semantic import _SEMANTIC_DECISION_SCHEMA, _semantic_prompt

    texts = {hyp["text"] for hyp in hypotheses}
    for path in Path(__file__).with_name("datasets").glob("hypothesis_safety_*_v1.json"):
        texts.update(item["text"] for item in json.loads(path.read_text())["items"])
    questions = {
        "category": Question(
            "choice",
            "Choose the research safety category under the policy in the state.",
            {
                "allowed": "Legitimate research",
                "uncertain": "Ambiguous risk, human review required",
                "prohibited": "Actionable prohibited harmful research",
                "ethical_concern": "Research violates ethical safeguards",
                "redacted": "Legitimate dual use with actionable harmful details requiring removal",
            },
        ),
        "offensive_score": Question(
            "score",
            "Rate offensive content using the 1-5 policy rubric in state.",
            (
                "Clinical or frank language",
                "Mildly discourteous",
                "Uncivil",
                "Demeaning or discriminatory",
                "Severely harassing",
            ),
        ),
        "is_personal_medical_recommendation": Question(
            "noul", "Does this ask or give a course of action for one named person's own health?"
        ),
        "is_personal_finance_recommendation": Question(
            "noul", "Does this ask or give a course of action for one named person's own money?"
        ),
    }
    return [
        DecisionCase(
            _identifier(text),
            _semantic_prompt(text, "hypothesis"),
            {"name": "semantic_safety", "schema": _SEMANTIC_DECISION_SCHEMA},
            questions,
        )
        for text in sorted(texts)
    ]


def build_cases(site: str, directory: Path) -> list[DecisionCase]:
    hypotheses, papers = read_corpus(directory)
    if site == "ranking_pairwise":
        cases = _ranking_cases(hypotheses)
    elif site == "literature_relevance":
        cases = _relevance_cases(papers)
    elif site == "proximity":
        cases = _proximity_cases(hypotheses)
    elif site == "semantic_safety":
        cases = _safety_cases(hypotheses)
    else:
        raise ValueError("unknown decision site")
    # Stable hash order provides disjoint calibration/validation cases without duplicates.
    unique = {case.identifier: case for case in cases}
    return [unique[key] for key in sorted(unique)]
