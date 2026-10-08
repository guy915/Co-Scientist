from co_scientist.platform.llm.decisions.types import Question

RELEVANCE_LEVELS = (
    "Unrelated",
    "Slightly related",
    "Partially relevant",
    "Strongly relevant",
    "Directly on point",
)


def relevance_questions(count: int, contexts: list[str] | None = None) -> dict[str, Question]:
    if not 1 <= count <= 10:
        raise ValueError("relevance batches contain one to ten candidates")
    if contexts is not None and len(contexts) != count:
        raise ValueError("each relevance question needs its candidate context")
    return {
        f"relevance_{number}": Question(
            "score",
            (
                "Score the sole candidate in this complete registered context:\n"
                + contexts[number - 1]
                if contexts is not None
                else f"How relevant is Candidate {number} to the research goal?"
            ),
            RELEVANCE_LEVELS,
        )
        for number in range(1, count + 1)
    }
