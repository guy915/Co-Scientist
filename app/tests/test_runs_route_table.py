"""Pin the ``/api/runs`` route table so router moves cannot change it.

The run endpoints are spread across ``runs_*`` sibling routers that
``app.runs`` stitches together. Moving a handler between those modules must
leave the served API untouched: same paths, methods, handler names, request
and response shape. FastAPI's own flattened view of the table is the OpenAPI
document, so that is what this snapshots rather than the private
``_IncludedRouter`` tree ``app.routes`` holds in FastAPI 0.138.

None of these routes declares a ``Depends``: authentication and ownership are
the ``app.main`` middleware keyed on the ``/api/runs`` prefix, so the handler's
module cannot affect them. A dependency added to one would surface here as an
extra parameter or a ``security`` entry.

The comparison is ordered. Registration order is first-match-wins between
routes whose templates overlap (``/demo`` against ``/{run_id}``) and is also
the order the API docs list, so it is part of what must not drift.
"""

from __future__ import annotations

# One operation per line so a diff names exactly which route changed; the
# generated operation ids are too long to wrap without hiding that.
# ruff: noqa: E501
from typing import Any

from app.main import app

# One row per operation:
# ``METHOD path | operationId | <in>:<param>[*] | request body | responses``
# where ``*`` marks a required parameter.
EXPECTED = [
    "POST /api/runs | create_run_api_runs_post |  | CreateRunRequest | 200,422",
    "GET /api/runs | list_runs_api_runs_get | query:limit |  | 200,422",
    "GET /api/runs/demo | list_demo_runs_api_runs_demo_get |  |  | 200",
    "GET /api/runs/{run_id} | get_run_api_runs__run_id__get | path:run_id* |  | 200,422",
    "PATCH /api/runs/{run_id} | rename_run_api_runs__run_id__patch | path:run_id* | RenameRunRequest | 200,422",
    "DELETE /api/runs/{run_id} | delete_run_api_runs__run_id__delete | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/start | start_run_api_runs__run_id__start_post | path:run_id* | StartRunRequest | 200,422",
    "POST /api/runs/{run_id}/cancel | cancel_run_api_runs__run_id__cancel_post | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/pause | pause_run_api_runs__run_id__pause_post | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/resume | resume_run_api_runs__run_id__resume_post | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/events | stream_events_api_runs__run_id__events_get | path:run_id*,query:after,query:stream |  | 200,422",
    "GET /api/runs/{run_id}/hypotheses | get_hypotheses_api_runs__run_id__hypotheses_get | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/hypotheses | add_human_hypothesis_api_runs__run_id__hypotheses_post | path:run_id* | HumanHypothesisRequest | 200,422",
    "GET /api/runs/{run_id}/evidence | get_evidence_api_runs__run_id__evidence_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/matches | get_matches_api_runs__run_id__matches_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/proximity | get_proximity_api_runs__run_id__proximity_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/reviews | get_reviews_api_runs__run_id__reviews_get | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/reviews | add_human_review_api_runs__run_id__reviews_post | path:run_id* | HumanReviewRequest | 200,422",
    "GET /api/runs/{run_id}/safety | get_safety_api_runs__run_id__safety_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/outcomes | get_hypothesis_outcomes_api_runs__run_id__outcomes_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/tasks | get_tasks_api_runs__run_id__tasks_get | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/safety/{decision_id}/adjudicate | adjudicate_safety_api_runs__run_id__safety__decision_id__adjudicate_post | path:run_id*,path:decision_id* | SafetyAdjudicationRequest | 200,422",
    "GET /api/runs/{run_id}/citations | get_citations_api_runs__run_id__citations_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/metrics | get_metrics_api_runs__run_id__metrics_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/logs | get_run_logs_api_runs__run_id__logs_get | path:run_id*,query:after_id,query:limit,query:min_level,query:q,query:verbose |  | 200,422",
    "GET /api/runs/{run_id}/claim-evidence | get_claim_evidence_api_runs__run_id__claim_evidence_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/knowledge-facts | get_knowledge_facts_api_runs__run_id__knowledge_facts_get | path:run_id*,query:kind,query:entity |  | 200,422",
    "GET /api/runs/{run_id}/supervisor-plan | get_supervisor_plan_api_runs__run_id__supervisor_plan_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/report | get_report_api_runs__run_id__report_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/report.md | get_report_markdown_api_runs__run_id__report_md_get | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/attachments | add_attachment_api_runs__run_id__attachments_post | path:run_id* | HumanAttachmentRequest | 200,422",
    "POST /api/runs/{run_id}/attachments/upload | upload_attachment_api_runs__run_id__attachments_upload_post | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/attachments/search | search_attachments_api_runs__run_id__attachments_search_get | path:run_id*,query:q* |  | 200,422",
    "POST /api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes | record_hypothesis_outcome_api_runs__run_id__hypotheses__hypothesis_id__outcomes_post | path:run_id*,path:hypothesis_id* | HypothesisOutcomeRequest | 201,422",
    "POST /api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes/{outcome_id}/refine | request_hypothesis_outcome_refinement_api_runs__run_id__hypotheses__hypothesis_id__outcomes__outcome_id__refine_post | path:run_id*,path:hypothesis_id*,path:outcome_id*,header:Idempotency-Key* |  | 202,422",
    "GET /api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes/{outcome_id}/refine | get_hypothesis_outcome_refinement_api_runs__run_id__hypotheses__hypothesis_id__outcomes__outcome_id__refine_get | path:run_id*,path:hypothesis_id*,path:outcome_id* |  | 200,422",
    "POST /api/runs/{run_id}/messages | send_message_api_runs__run_id__messages_post | path:run_id* | SendMessageRequest | 200,422",
    "GET /api/runs/{run_id}/messages | list_messages_api_runs__run_id__messages_get | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/messages/ask | ask_question_api_runs__run_id__messages_ask_post | path:run_id* | AskRequest | 200,422",
    "POST /api/runs/{run_id}/messages/started | announce_start_api_runs__run_id__messages_started_post | path:run_id* | StartAnnouncementRequest | 200,422",
]


def describe_routes() -> list[str]:
    """Flatten the served ``/api/runs`` operations out of OpenAPI."""
    rows = []
    for path, operations in app.openapi()["paths"].items():
        for method, op in operations.items():
            if op.get("tags") == ["runs"]:
                rows.append(_describe(method.upper(), path, op))
    return rows


def _describe(method: str, path: str, op: dict[str, Any]) -> str:
    params = ",".join(
        f"{p['in']}:{p['name']}{'*' if p['required'] else ''}"
        for p in op.get("parameters", [])
    )
    body = (
        op.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("$ref", "")
        .rsplit("/", 1)[-1]
    )
    codes = ",".join(sorted(op["responses"]))
    return (
        f"{method} {path} | {op['operationId']} | {params} | {body} | {codes}"
    )


def test_run_route_table_is_unchanged() -> None:
    """Every run operation keeps its path, method, handler, shape and slot."""
    assert describe_routes() == EXPECTED
