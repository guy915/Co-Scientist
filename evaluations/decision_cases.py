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


def _identifier(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


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
                for hyp in conn.execute("SELECT * FROM hypotheses WHERE run_id=?", (row["id"],)):
                    text = "\n".join(
                        str(hyp[key] or "")
                        for key in (
                            "statement",
                            "mechanism",
                            "expected_effect",
                            "experimental_context",
                        )
                    )
                    if text.strip():
                        hypotheses[_identifier(goal + text)] = {"goal": goal, "text": text}
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
        prompt, schema = get_ranking_prompt(
            a["goal"], RankingSide(a["text"]), RankingSide(b["text"])
        )
        reverse, _ = get_ranking_prompt(a["goal"], RankingSide(b["text"]), RankingSide(a["text"]))
        assert schema is not None
        cases.append(
            DecisionCase(
                _identifier(prompt),
                prompt,
                schema,
                {"winner": question},
                reverse,
                (_identifier(a["text"]), _identifier(b["text"])),
            )
        )
    return cases


def _relevance_cases(papers: list[dict[str, Any]]) -> list[DecisionCase]:
    from co_scientist.platform.llm.decisions.relevance import relevance_questions
    from co_scientist.platform.retrieval.evidence.relevance import _build_candidates_block
    from co_scientist.science.prompts.literature import get_literature_review_relevance_batch_prompt
    from co_scientist.science.schemas import LITERATURE_RELEVANCE_BATCH_SCHEMA

    by_goal: dict[str, list[dict[str, Any]]] = {}
    for paper in papers:
        by_goal.setdefault(paper["goal"], []).append(paper)
    cases = []
    for goal, group in by_goal.items():
        ordered = sorted(group, key=lambda paper: _identifier(json.dumps(paper, sort_keys=True)))
        for start in range(0, len(ordered), 10):
            batch = ordered[start : start + 10]
            ranked = {str(i): paper for i, paper in enumerate(batch)}
            prompt = get_literature_review_relevance_batch_prompt(
                goal, _build_candidates_block(list(ranked), ranked)
            )
            cases.append(
                DecisionCase(
                    _identifier(prompt),
                    prompt,
                    LITERATURE_RELEVANCE_BATCH_SCHEMA,
                    relevance_questions(len(batch)),
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
