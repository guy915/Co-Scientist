"""Explicit recovery of the two incomplete scope pairs; no automatic retry loop."""


def schedule(order, trials, attempt):
    if attempt:
        if attempt != "recovery1" or trials != [2, 3]:
            raise ValueError(
                "Only the recorded recovery1 of pairs 2 and 3 is authorized"
            )
    elif trials != [1, 2, 3]:
        raise ValueError("Partial execution requires the recorded recovery attempt")
    if order != [
        ["baseline", "candidate"],
        ["candidate", "baseline"],
        ["baseline", "candidate"],
    ]:
        raise ValueError("Frozen counterbalanced order changed")
    return [
        (trial, order[trial - 1], f"-{attempt}" if attempt else "") for trial in trials
    ]
