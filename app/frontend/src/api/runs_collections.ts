import type {
  ClaimEvidenceRow,
  Evidence,
  Hypothesis,
  HypothesisOutcome,
  HypothesisOutcomeInput,
  MatchRow,
  Review,
  SafetyDecision,
} from './wire_science';
import type {Report, SharedGoalReport} from './wire_reports';
import {
  API_BASE_URL,
  clientHeaders,
  fetchField,
  fetchJson,
  jsonRequest,
  parseJson,
  fetchWithSession,
} from './runs_http';

/** A durable owner-authorized request to refine one outcome's parent. */
export interface OutcomeRefinementAction {
  action_id: string;
  run_id: string;
  outcome_id: string;
  hypothesis_id: string;
  task_idempotency_key: string;
  checkpoint_seq: number;
  context_codepoints: number;
  status: string;
  child_hypothesis_id: string | null;
  created_at: number;
  replayed: boolean;
}

/** One saved Supervisor decision in the durable allocation ledger. */
export interface SupervisorAllocation {
  id: number;
  run_id: string;
  seq: number;
  iteration: number;
  task_type: string;
  status: string;
  reason: string;
  planner_reason: string | null;
  priority: number | null;
  termination_reason: string | null;
  created_at: number;
}

/** The Supervisor plan snapshot, absent until the first checkpoint commits. */
export interface SupervisorPlanRecord {
  run_id: string;
  plan: Record<string, unknown>;
  orchestrator_state: Record<string, unknown>;
  decision_provenance: string | null;
  termination_reason: string | null;
  created_at: number;
  updated_at: number;
}

/** The persisted plan and append-ordered allocation rows for one run. */
export interface SupervisorPlanResponse {
  plan: SupervisorPlanRecord | null;
  allocations: SupervisorAllocation[];
}

/** Most run collections use their path segment as the response key. */
function getRunList<T>(id: string, key: string): Promise<T[]> {
  return fetchField<string, T[]>(`/api/runs/${id}/${key}`, key, {
    headers: clientHeaders(),
  });
}

export function getHypotheses(id: string): Promise<Hypothesis[]> {
  return getRunList<Hypothesis>(id, 'hypotheses');
}

export function getEvidence(id: string): Promise<Evidence[]> {
  return getRunList<Evidence>(id, 'evidence');
}

export function getMatches(id: string): Promise<MatchRow[]> {
  return getRunList<MatchRow>(id, 'matches');
}

export function getReviews(id: string): Promise<Review[]> {
  return getRunList<Review>(id, 'reviews');
}

/** Fetch the versioned safety audit trail for a run. */
export function getSafety(id: string): Promise<SafetyDecision[]> {
  return getRunList<SafetyDecision>(id, 'safety');
}

/** This collection's response key differs from its path segment. */
export function getClaimEvidence(id: string): Promise<ClaimEvidenceRow[]> {
  return fetchField<'claim_evidence', ClaimEvidenceRow[]>(
    `/api/runs/${id}/claim-evidence`,
    'claim_evidence',
    {headers: clientHeaders()},
  );
}

/** Fetch the persisted Supervisor plan and ordered allocation ledger. */
export function getSupervisorPlan(id: string): Promise<SupervisorPlanResponse> {
  return fetchJson(`/api/runs/${id}/supervisor-plan`, {
    headers: clientHeaders(),
  });
}

/** Fetch scientist-recorded empirical outcomes for a run. */
export function getHypothesisOutcomes(
  id: string,
): Promise<HypothesisOutcome[]> {
  return getRunList<HypothesisOutcome>(id, 'outcomes');
}

/** Append a scientist-recorded observation to one hypothesis. */
export function addHypothesisOutcome(
  runId: string,
  hypothesisId: string,
  input: HypothesisOutcomeInput,
): Promise<HypothesisOutcome> {
  return fetchJson(
    `/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes`,
    jsonRequest(input, true),
  );
}

/** Fetch one existing outcome refinement action for its owner. */
export function getHypothesisOutcomeRefinement(
  runId: string,
  hypothesisId: string,
  outcomeId: string,
): Promise<OutcomeRefinementAction> {
  return fetchJson(
    `/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes/${outcomeId}/refine`,
    {headers: clientHeaders()},
  );
}

/** Request or replay one owner's outcome-to-parent refinement intent. */
export function requestHypothesisOutcomeRefinement(
  runId: string,
  hypothesisId: string,
  outcomeId: string,
): Promise<OutcomeRefinementAction> {
  const idempotencyKey = `outcome-refinement:${runId}:${hypothesisId}:${outcomeId}`;
  return fetchJson(
    `/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes/${outcomeId}/refine`,
    {
      method: 'POST',
      headers: {
        ...clientHeaders(),
        'Idempotency-Key': idempotencyKey,
      },
    },
  );
}

/** Upload and index a private scientific document for subsequent tasks. */
export function uploadRunDocument(
  runId: string,
  file: File,
): Promise<{
  id: string;
  indexed: boolean;
  sha256: string;
  byte_size: number;
  mime_type: string;
  extraction_tool: string;
}> {
  const body = new FormData();
  body.set('file', file);
  body.set('consent', 'true');
  return fetchJson(`/api/runs/${runId}/attachments/upload`, {
    method: 'POST',
    headers: clientHeaders(),
    body,
  });
}

/** A 404 means the report has not been generated yet. */
export async function getReport(id: string): Promise<Report | null> {
  const res = await fetchWithSession(`${API_BASE_URL}/api/runs/${id}/report`, {
    headers: clientHeaders(),
  });
  if (res.status === 404) return null; // no report yet, not an error
  return parseJson<Report>(res);
}

/** Loads a public read-only Goal Report without a client ownership header. */
export function getSharedGoalReport(token: string): Promise<SharedGoalReport> {
  return fetchJson(`/api/shared/${token}`);
}
