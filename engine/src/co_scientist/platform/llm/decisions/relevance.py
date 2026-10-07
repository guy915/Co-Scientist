from co_scientist.platform.llm.decisions.types import Question

RELEVANCE_LEVELS = (
    "Unrelated",
    "Slightly related",
    "Partially relevant",
    "Strongly relevant",
    "Directly on point",
)


def relevance_questions(count: int) -> dict[str, Question]:
    if not 1 <= count <= 10:
        raise ValueError("relevance batches contain one to ten candidates")
    return {
        f"relevance_{number}": Question(
            "score",
            f"How relevant is Candidate {number} to the research goal?",
            RELEVANCE_LEVELS,
        )
        for number in range(1, count + 1)
    }
