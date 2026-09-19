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


def evaluate_model_scope_controls(dataset, model, *, before_mode=None):
    """Run both real assessor paths after the caller configures free admission.

    Capture usage separately for each interface. The caller still binds helper
    and input hashes, observes physical requests, and verifies model identity.
    """
    from app.claim_verifier import make_llm_assessor
    from app.claim_verifier_batch import make_llm_batch_assessor
    from evaluations._panel_identity import capture_panel

    results = {}
    for batch, factory in ((False, make_llm_assessor), (True, make_llm_batch_assessor)):
        if before_mode is not None:
            before_mode("batch_single_claim" if batch else "single")
        assessor, assessor_id = factory(model)
        with capture_panel(
            "citation_entailment", dataset, model, live=True
        ) as evidence:
            result = evaluate_scope_controls(
                dataset, assessor, assessor_id, batch=batch
            )
        results[result["mode"]] = {**evidence, **result}
    return results


def validate_scope_evidence(record, dataset):
    """Validate complete live evidence; return scientific control acceptance.

    Parent comparator verifies every physical request's price caps and usage,
    matched capture identities, and frozen source/input hashes.
    """
    panels = record["scope_controls"]
    if set(panels) != {"single", "batch_single_claim"}:
        raise ValueError("Missing scope modes")
    expected = [item["id"] for item in dataset["items"]]
    if not expected or len(set(expected)) != len(expected):
        raise ValueError("Invalid scope items")
    accepted = True
    for mode, panel in panels.items():
        checks = panel["checks"]
        if panel["mode"] != mode or [c["id"] for c in checks] != expected:
            raise ValueError("Missing or reordered scope items")
        usage = panel["usage_evidence"]
        physical = [
            r for r in record["physical_requests"] if r["phase"] == "scope_" + mode
        ]
        if (
            len(physical) < len(expected)
            or usage["physical_calls"] != len(physical)
            or usage["observed_models"] != [record["requested_model"]]
            or usage["unobserved_model_calls"] != 0
            or usage["unreported_usage_calls"] != 0
        ):
            raise ValueError("Incomplete scope physical usage evidence")
        accepted &= not usage["recorded_deterministic_fallbacks"]
        for check, item in zip(checks, dataset["items"]):
            accepted &= (
                check["passed"] is True
                and check["label"] in item["allowed_labels"]
                and check["allowed_labels"] == item["allowed_labels"]
                and check["quotes_valid"] is True
                and check["nonempty_assessor_invocations"] > 0
                and check["verification_method"]
                in {
                    "model_primary",
                    "model_opposition_verified",
                    "model_opposition_unconfirmed",
                }
            )
    return bool(accepted)
