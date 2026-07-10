"""Engine adapter — chooses real engine or mock workflow at runtime.

Logic:
- Provider = `mock` if `COSCIENTIST_FORCE_MOCK=1`, OR no LLM key is set, OR the
  `co_scientist` package can't be imported. Otherwise `engine`.
- Real-engine path imports lazily so the app boots even when the engine isn't
  installed yet (e.g. during initial setup).

The `mock` provider is the only one we exercise in CI / tests.

The package is split by concern: ``provider`` (mock/engine selection,
diagnostics, and the lazy engine import), ``events`` (engine-node to
canonical event/milestone translation), ``opts`` (run-config and steering
translation into engine opts), ``drain`` (final-state persistence into the
store), ``engine_stream`` (the real-engine streaming loop), and ``workflow``
(the shared ``run_workflow`` boundary with the intake safety gate). This
module re-exports the full former ``app.engine_adapter`` namespace —
including the private helpers exercised by tests — so callers keep using
``from app import engine_adapter`` unchanged.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import logging

from app.engine_adapter.drain import (
    _article_coalesced_fields as _article_coalesced_fields,
)
from app.engine_adapter.drain import _citation_map as _citation_map
from app.engine_adapter.drain import _citation_url as _citation_url
from app.engine_adapter.drain import (
    _derive_hypothesis_identity as _derive_hypothesis_identity,
)
from app.engine_adapter.drain import (
    _ensure_citation_evidence_id as _ensure_citation_evidence_id,
)
from app.engine_adapter.drain import _final_state_dict as _final_state_dict
from app.engine_adapter.drain import _final_state_list as _final_state_list
from app.engine_adapter.drain import (
    _hypothesis_grounding_text as _hypothesis_grounding_text,
)
from app.engine_adapter.drain import (
    _matchup_loser_engine_id as _matchup_loser_engine_id,
)
from app.engine_adapter.drain import (
    _persist_deep_verification_review as _persist_deep_verification_review,
)
from app.engine_adapter.drain import (
    _persist_engine_citations as _persist_engine_citations,
)
from app.engine_adapter.drain import (
    _persist_engine_evidence as _persist_engine_evidence,
)
from app.engine_adapter.drain import (
    _persist_engine_hypothesis as _persist_engine_hypothesis,
)
from app.engine_adapter.drain import (
    _persist_engine_hypothesis_row as _persist_engine_hypothesis_row,
)
from app.engine_adapter.drain import (
    _persist_engine_matches as _persist_engine_matches,
)
from app.engine_adapter.drain import (
    _persist_engine_review_rows as _persist_engine_review_rows,
)
from app.engine_adapter.drain import (
    _persist_engine_reviews as _persist_engine_reviews,
)
from app.engine_adapter.drain import (
    _persist_final_state as _persist_final_state,
)
from app.engine_adapter.drain import (
    _persist_hypothesis_state as _persist_hypothesis_state,
)
from app.engine_adapter.drain import (
    _resolve_match_sides as _resolve_match_sides,
)
from app.engine_adapter.drain import _score_or_none as _score_or_none
from app.engine_adapter.engine_stream import (
    _emit_cancelled_event as _emit_cancelled_event,
)
from app.engine_adapter.engine_stream import (
    _emit_engine_failure as _emit_engine_failure,
)
from app.engine_adapter.engine_stream import (
    _emit_engine_node_event as _emit_engine_node_event,
)
from app.engine_adapter.engine_stream import (
    _emit_engine_running as _emit_engine_running,
)
from app.engine_adapter.engine_stream import (
    _merge_engine_state as _merge_engine_state,
)
from app.engine_adapter.engine_stream import (
    _new_engine_final_state as _new_engine_final_state,
)
from app.engine_adapter.engine_stream import (
    _persist_and_report as _persist_and_report,
)
from app.engine_adapter.engine_stream import (
    _real_engine_stream as _real_engine_stream,
)
from app.engine_adapter.engine_stream import (
    _run_engine_and_report as _run_engine_and_report,
)
from app.engine_adapter.engine_stream import (
    _run_engine_provider as _run_engine_provider,
)
from app.engine_adapter.engine_stream import (
    _stream_engine_nodes as _stream_engine_nodes,
)
from app.engine_adapter.events import (
    _ENGINE_PIPELINE_AGENTS as _ENGINE_PIPELINE_AGENTS,
)
from app.engine_adapter.events import (
    _MILESTONE_BUILDERS as _MILESTONE_BUILDERS,
)
from app.engine_adapter.events import _PAYLOAD_BUILDERS as _PAYLOAD_BUILDERS
from app.engine_adapter.events import (
    _canonical_engine_payload as _canonical_engine_payload,
)
from app.engine_adapter.events import (
    _canonical_event_type as _canonical_event_type,
)
from app.engine_adapter.events import (
    _evolve_payload_extra as _evolve_payload_extra,
)
from app.engine_adapter.events import _format_milestone as _format_milestone
from app.engine_adapter.events import (
    _generate_payload_extra as _generate_payload_extra,
)
from app.engine_adapter.events import (
    _literature_review_payload_extra as _literature_review_payload_extra,
)
from app.engine_adapter.events import _milestone_evolve as _milestone_evolve
from app.engine_adapter.events import (
    _milestone_generate as _milestone_generate,
)
from app.engine_adapter.events import (
    _milestone_meta_review as _milestone_meta_review,
)
from app.engine_adapter.events import _milestone_ranking as _milestone_ranking
from app.engine_adapter.events import (
    _milestone_supervisor_plan as _milestone_supervisor_plan,
)
from app.engine_adapter.events import (
    _ranking_payload_extra as _ranking_payload_extra,
)
from app.engine_adapter.events import (
    _supervisor_plan_payload_extra as _supervisor_plan_payload_extra,
)
from app.engine_adapter.opts import _append_if as _append_if
from app.engine_adapter.opts import _build_engine_opts as _build_engine_opts
from app.engine_adapter.opts import _build_generator as _build_generator
from app.engine_adapter.opts import _clean_list_field as _clean_list_field
from app.engine_adapter.opts import (
    _drain_pre_run_steering as _drain_pre_run_steering,
)
from app.engine_adapter.opts import (
    _fold_steering_preferences as _fold_steering_preferences,
)
from app.engine_adapter.opts import (
    _resolve_literature_review_toggle as _resolve_literature_review_toggle,
)
from app.engine_adapter.opts import (
    _setup_opts_from_cfg as _setup_opts_from_cfg,
)
from app.engine_adapter.opts import (
    _steering_preference_part as _steering_preference_part,
)
from app.engine_adapter.provider import _engine_importable as _engine_importable
from app.engine_adapter.provider import _engine_src as _engine_src
from app.engine_adapter.provider import _has_provider_key as _has_provider_key
from app.engine_adapter.provider import (
    _import_hypothesis_generator as _import_hypothesis_generator,
)
from app.engine_adapter.provider import select_provider as select_provider
from app.engine_adapter.provider import system_status as system_status
from app.engine_adapter.workflow import (
    _dispatch_provider as _dispatch_provider,
)
from app.engine_adapter.workflow import (
    _emit_mock_milestone as _emit_mock_milestone,
)
from app.engine_adapter.workflow import (
    _select_provider_stream as _select_provider_stream,
)
from app.engine_adapter.workflow import (
    _stream_mock_provider as _stream_mock_provider,
)
from app.engine_adapter.workflow import run_workflow as run_workflow

logger = logging.getLogger(__name__)
