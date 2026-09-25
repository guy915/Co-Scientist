import type {HypothesisOutcome} from '@/api/runs';

export function canUseOutcomeRefinement(
  allowed: boolean,
  readOnly: boolean,
  hasResearcherSession: boolean,
): boolean {
  return allowed && !readOnly && hasResearcherSession;
}

export function outcomeRefinementContext(
  allowed: boolean,
  runId?: string,
  hypothesisId?: string,
): {runId: string; hypothesisId: string} | undefined {
  if (!allowed || !runId || !hypothesisId) return undefined;
  return {runId, hypothesisId};
}

export function outcomeHypothesisTitle(
  outcome: HypothesisOutcome,
  titleById?: Map<string, string>,
): string {
  return (
    titleById?.get(outcome.hypothesis_id) ??
    outcome.hypothesis_snapshot?.title ??
    outcome.hypothesis_id
  );
}

export function hasEmptyOutcomeCollection(
  loading: boolean,
  error: string | null,
  count: number,
): boolean {
  return !loading && !error && count === 0;
}
