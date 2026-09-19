"""Paced live challenge and historical controls through public assessors."""

import asyncio
import datetime
import hashlib
import importlib
import json
import os
import re
import time
import types
import sys
from pathlib import Path

import litellm
from evaluations import citation_eval
from qualification_sources import imported_sources

_REQUESTS = []
_ASSESSMENTS = []
_TRANSPORT = litellm.acompletion
_LAST_START = 0.0
_CONTROLLED_PRIMARY = None
_PHASE = "challenge"
_SOURCE_MANIFEST = None
_SOURCE_ROOT = None
_SOURCE_ARM = None
_VERIFIED_IMPORTS = {}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def observed_transport(**kwargs):
    global _LAST_START, _CONTROLLED_PRIMARY
    if _CONTROLLED_PRIMARY is not None:
        payload, _CONTROLLED_PRIMARY = _CONTROLLED_PRIMARY, None
        return types.SimpleNamespace(
            model="controlled-primary",
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content=json.dumps(payload))
                )
            ],
        )
    if _SOURCE_MANIFEST is not None:
        if "scope_helper_sha256" in _SOURCE_MANIFEST:
            for name, field in (
                ("scope_controls.py", "scope_helper_sha256"),
                ("partial-support-scope-controls.json", "scope_controls_sha256"),
            ):
                if digest(Path(__file__).with_name(name)) != _SOURCE_MANIFEST[field]:
                    raise RuntimeError("Scope observer or input drift")
        _VERIFIED_IMPORTS.update(
            imported_sources(
                _SOURCE_ROOT, _SOURCE_MANIFEST["arms"][_SOURCE_ARM]["verified_sources"]
            )
        )
    await asyncio.sleep(max(0, 4 - (time.monotonic() - _LAST_START)))
    _LAST_START = time.monotonic()
    record = {
        k: kwargs.get(k)
        for k in ("model", "max_tokens", "extra_body", "response_format")
    }
    record["phase"] = _PHASE
    record["started_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    record["prompt_sha256"] = hashlib.sha256(
        json.dumps(kwargs.get("messages"), sort_keys=True).encode()
    ).hexdigest()
    _REQUESTS.append(record)
    response = await _TRANSPORT(**kwargs)
    record["response_model"] = getattr(response, "model", None)
    record["content"] = response.choices[0].message.content
    usage = getattr(response, "usage", None)
    record["usage"] = (
        usage.model_dump(mode="json") if hasattr(usage, "model_dump") else usage
    )
    record["finish_reason"] = getattr(response.choices[0], "finish_reason", None)
    return response


def install_assessment_observer(root):
    from app import claims

    original = claims.assess_claim

    def observed(claim, passages, **kwargs):
        start = len(_REQUESTS)
        result = original(claim, passages, **kwargs)
        _ASSESSMENTS.append(
            {
                "phase": _PHASE,
                "claim": claim,
                "label": result.label.value,
                "verification_method": getattr(
                    result, "verification_method", "legacy_unknown"
                ),
                "physical_request_indices": list(range(start, len(_REQUESTS))),
                "supporting_quotes": [s.quote for s in result.supporting_passages],
                "contradicting_quotes": [
                    s.quote for s in result.contradicting_passages
                ],
            }
        )
        return result

    claims.assess_claim = observed
    names = [
        "evaluations.citation_eval",
        "app.claim_verifier",
        "app.claims_span",
        "co_scientist.llm_request",
    ]
    if (root / "app/app/claim_verifier_opposition.py").exists():
        names.append("app.claim_verifier_opposition")
    sources = {}
    for name in names:
        path = Path(importlib.import_module(name).__file__).resolve()
        if not path.is_relative_to(root):
            raise RuntimeError(f"snapshot import escaped: {name}")
        sources[name] = {"path": str(path.relative_to(root)), "sha256": digest(path)}
    sources["opposition_module_present"] = "app.claim_verifier_opposition" in sources
    return sources


def historical_controls(dataset):
    from app.claim_verifier import make_llm_assessor
    from app.claims import as_passages, assess_claim
    from evaluations._panel_identity import capture_panel

    global _PHASE, _CONTROLLED_PRIMARY
    _PHASE = "historical_full_live"
    assessor, assessor_id = make_llm_assessor(os.environ["MODEL_NAME"])
    with capture_panel(
        "citation_entailment", dataset, os.environ["MODEL_NAME"], live=True
    ) as evidence:
        results = [
            assess_claim(
                item["claim"],
                as_passages(item["passages"]),
                assessor=assessor,
                assessor_id=assessor_id,
            )
            for item in dataset["items"]
        ]
    checks = [
        {
            "id": item["id"],
            "label": result.label.value,
            "verification_method": getattr(
                result, "verification_method", "legacy_unknown"
            ),
            "passed": result.label.value in item["allowed_labels"],
        }
        for item, result in zip(dataset["items"], results)
    ]
    # This separate experiment controls the first model response; only the
    # verification request is live. Do not include it in live panel telemetry.
    _PHASE = "controlled_primary_live_verifier"
    item = next(
        i
        for i in dataset["items"]
        if i["id"] == "test_confirmatory_quote_does_not_yield_contradiction"
    )
    _CONTROLLED_PRIMARY = {
        "label": "contradicts",
        "supporting": [],
        "contradicting": [{"passage": 1, "quote": item["passages"][0]}],
    }
    start = len(_REQUESTS)
    result = assess_claim(
        item["claim"],
        as_passages(item["passages"]),
        assessor=assessor,
        assessor_id=assessor_id,
    )
    return {**evidence, "checks": checks, "passed": all(c["passed"] for c in checks)}, {
        "mode": _PHASE,
        "id": item["id"],
        "primary_response_controlled": True,
        "label": result.label.value,
        "verification_method": getattr(result, "verification_method", "legacy_unknown"),
        "passed": result.label.value in item["allowed_labels"],
        "live_verifier_request_indices": list(range(start, len(_REQUESTS))),
        "note": "The primary completion is simulated and excluded from physical_requests. Only listed verifier requests are live.",
    }


if __name__ == "__main__":
    root = Path(
        os.environ.get("QUALIFICATION_ROOT", Path(__file__).resolve().parents[4])
    ).resolve()
    record = {
        "source_commit": os.environ["QUALIFICATION_REVISION"],
        "runtime": {"executable": sys.executable, "python": sys.version},
        "probe_sha256": digest(Path(__file__)),
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "requested_model": os.environ["MODEL_NAME"],
        "trial": int(os.environ["QUALIFICATION_TRIAL"]),
        "minimum_physical_start_spacing_seconds": 4,
    }
    if os.environ.get("QUALIFICATION_MANIFEST"):
        manifest_path = Path(os.environ["QUALIFICATION_MANIFEST"])
        _SOURCE_MANIFEST = json.loads(manifest_path.read_text())
        _SOURCE_ROOT = root
        _SOURCE_ARM = os.environ["QUALIFICATION_ARM"]
        record["source_manifest_sha256"] = digest(manifest_path)
        record["source_revisions"] = _SOURCE_MANIFEST["arms"][_SOURCE_ARM][
            "subtree_revisions"
        ]
        record["source_guard_sha256"] = digest(
            Path(__file__).with_name("qualification_sources.py")
        )
        record["challenge_sha256"] = digest(
            root / "evaluations/datasets/citation_entailment_challenge_v1.json"
        )
    original_factory = citation_eval._build_llm_assessor

    def observed_factory():
        result = original_factory()
        record["imported_sources"] = install_assessment_observer(root)
        return result

    citation_eval._build_llm_assessor = observed_factory
    litellm.acompletion = observed_transport
    try:
        from co_scientist.llm_free_catalog import current_catalog, verify_model

        raw = os.environ["MODEL_NAME"].removeprefix("openrouter/")
        catalog = current_catalog()
        verify_model(raw, catalog)
        record["eligibility"] = {
            k: catalog[raw].get(k)
            for k in ("id", "pricing", "architecture", "supported_parameters")
        }
        record["report"] = citation_eval.run(
            use_llm=True,
            dataset_path=root
            / "evaluations/datasets/citation_entailment_challenge_v1.json",
        )
        if os.environ.get("QUALIFICATION_CONTROLS"):
            path = Path(os.environ["QUALIFICATION_CONTROLS"])
            controls = json.loads(path.read_text())
            record["controls_sha256"] = digest(path)
            record["historical_controls"], record["controlled_primary"] = (
                historical_controls(controls)
            )
        if os.environ.get("QUALIFICATION_SCOPE_CONTROLS"):
            from scope_controls import evaluate_model_scope_controls

            path = Path(os.environ["QUALIFICATION_SCOPE_CONTROLS"])
            record["scope_controls_sha256"] = digest(path)
            record["scope_helper_sha256"] = digest(
                Path(__file__).with_name("scope_controls.py")
            )
            if _SOURCE_MANIFEST is None or any(
                record[key] != _SOURCE_MANIFEST[key]
                for key in ("scope_controls_sha256", "scope_helper_sha256")
            ):
                raise RuntimeError("Scope inputs or helper differ from manifest")

            def scope_phase(mode):
                global _PHASE
                _PHASE = "scope_" + mode

            record["scope_controls"] = evaluate_model_scope_controls(
                json.loads(path.read_text()),
                os.environ["MODEL_NAME"],
                before_mode=scope_phase,
            )
    except Exception as exc:
        record["error_type"] = type(exc).__name__
        record["error"] = re.sub(
            r"user_[A-Za-z0-9]+",
            "[redacted-account]",
            str(exc).replace(os.environ["OPENROUTER_API_KEY"], "[redacted]"),
        )[:2000]
    if _SOURCE_MANIFEST is not None:
        try:
            _VERIFIED_IMPORTS.update(
                imported_sources(
                    root, _SOURCE_MANIFEST["arms"][_SOURCE_ARM]["verified_sources"]
                )
            )
            record["verified_project_imports"] = _VERIFIED_IMPORTS
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            record["error"] = str(exc)[:2000]
    record["physical_requests"] = _REQUESTS
    record["assessments"] = _ASSESSMENTS
    record["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    Path(os.environ["QUALIFICATION_OUTPUT"]).write_text(
        json.dumps(record, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "model": record["requested_model"],
                "error_type": record.get("error_type"),
                "metrics": record.get("report", {}).get("metrics"),
                "gates": record.get("report", {}).get("production_gates"),
            }
        )
    )
