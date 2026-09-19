"""Evaluate prospective scope controls through public single/batch assessors.

The caller supplies the configured assessor and owns model telemetry, source
identity and zero-cost admission. This module neither loads credentials nor
constructs a model. Batch-mode controls use one claim at a time to keep another
control's evidence from answering a deliberately unsupported claim.
"""


def evaluate_scope_controls(dataset, assessor, assessor_id, *, batch=False):
    # The live runner must configure admission before any app import.
    from app.claims import as_passages, assess_claim, assess_claims_batch

    if not dataset.get("items"):
        raise ValueError("Scope controls cannot be empty")
    checks = []
    for item in dataset["items"]:
        passages = as_passages(item["passages"])
        invocations = []

        def observed(*args):
            invocations.append(bool(args[-1]))
            return assessor(*args)

        if batch:
            result = assess_claims_batch(
                [item["claim"]],
                passages,
                batch_assessor=observed,
                assessor_id=assessor_id,
            )[0]
        else:
            result = assess_claim(
                item["claim"],
                passages,
                assessor=observed,
                assessor_id=assessor_id,
            )
        label = result.label.value
        spans = (
            result.contradicting_passages
            if label == "contradicts"
            else result.supporting_passages
        )
        texts = {p.evidence_id: p.text for p in passages}
        quotes = [
            {
                "evidence_id": s.evidence_id,
                "quote": s.quote,
                "start": s.start,
                "end": s.end,
            }
            for s in spans
        ]
        located = bool(spans) and all(
            s.quote and texts.get(s.evidence_id, "")[s.start : s.end] == s.quote
            for s in spans
        )
        quotes_valid = (
            bool(located) if label in {"supports", "partial", "contradicts"} else True
        )
        method = getattr(result, "verification_method", "legacy_unknown")
        checks.append(
            {
                "id": item["id"],
                "label": label,
                "allowed_labels": item["allowed_labels"],
                "assessor_invocations": len(invocations),
                "nonempty_assessor_invocations": sum(invocations),
                "verification_method": method,
                "quotes": quotes,
                "quotes_valid": quotes_valid,
                "passed": any(invocations)
                and label in item["allowed_labels"]
                and quotes_valid
                and method
                in {
                    "model_primary",
                    "model_opposition_verified",
                    "model_opposition_unconfirmed",
                },
            }
        )
    return {
        "mode": "batch_single_claim" if batch else "single",
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
        "limitation": "Batch controls preserve evidence isolation using one claim per call; multi-claim behavior requires separate workflow verification.",
    }
