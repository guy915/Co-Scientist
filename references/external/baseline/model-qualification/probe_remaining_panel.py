"""Invoke an existing panel once with retained physical-request evidence."""

import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

from evaluations._live_config import configure_live_environment

MODEL = configure_live_environment()

from co_scientist.llm_free_catalog import current_catalog, verify_model  # noqa: E402
from co_scientist.llm_call_budget import scoped_llm_call_budget  # noqa: E402
import probe_citation_panel as observer  # noqa: E402

panel = os.environ["QUALIFICATION_PANEL"]
if panel not in {"usefulness", "ranking"}:
    raise ValueError("Unknown qualification panel")
output = Path(os.environ["QUALIFICATION_OUTPUT"])
record = {
    "panel": panel,
    "trial": int(os.environ["QUALIFICATION_TRIAL"]),
    "requested_model": MODEL,
    "source_commit": os.environ["QUALIFICATION_REVISION"],
    "invocation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "observer_sha256": observer.digest(Path(observer.__file__)),
    "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
with output.open("x") as artifact:
    try:
        catalog = current_catalog()
        raw_model = MODEL.removeprefix("openrouter/")
        verify_model(raw_model, catalog)
        record["eligibility"] = catalog[raw_model]
        observer.litellm.acompletion = observer.observed_transport
        with scoped_llm_call_budget(
            f"qualification:{output.resolve()}", 20 if panel == "usefulness" else 60
        ):
            if panel == "usefulness":
                from evaluations import citation_usefulness_eval as evaluator

                record["report"] = evaluator.run_llm(evaluator.load_dataset(), MODEL)
            else:
                from evaluations import elo_concordance_eval as evaluator

                record["report"] = evaluator.run(use_llm=True)
    except Exception as exc:
        record["error_type"] = type(exc).__name__
        record["error"] = str(exc).replace(
            os.environ["OPENROUTER_API_KEY"], "[redacted]"
        )[:2000]
    finally:
        record["physical_requests"] = observer._REQUESTS
        record["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        artifact.write(json.dumps(record, indent=2) + "\n")
print(
    json.dumps(
        {
            "panel": panel,
            "error_type": record.get("error_type"),
            "requests": len(observer._REQUESTS),
        }
    ),
    flush=True,
)
sys.exit(1 if "error_type" in record else 0)
