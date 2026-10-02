import {
  getClaimEvidence,
  getEvidence,
  getHypotheses,
  getMatches,
  getReport,
  getReviews,
  getRun,
  getSafety,
  type SafetyDecision,
} from '@/api/runs';
import type {RunDataKey} from './run_detail_resources';

// Fetches the run row plus whichever collections `keys` selects (every
// collection when `keys` is omitted), in parallel.
async function fetchRunData(id: string, keys?: ReadonlySet<RunDataKey>) {
  const fetchIfWanted = <T>(
    key: RunDataKey,
    fetcher: (id: string) => Promise<T>,
  ): Promise<T> | undefined =>
    !keys || keys.has(key) ? fetcher(id) : undefined;
  // Older compatible backends may not expose the safety-audit endpoint yet;
  // the rest of a Goal Report must remain readable during rolling upgrades.
  const getSafetyCompatible = (runId: string) =>
    getSafety(runId).catch((): SafetyDecision[] => []);
  const [
    run,
    hypotheses,
    evidence,
    matches,
    reviews,
    claimEvidence,
    safety,
    report,
  ] = await Promise.all([
    getRun(id),
    fetchIfWanted('hypotheses', getHypotheses),
    fetchIfWanted('evidence', getEvidence),
    fetchIfWanted('matches', getMatches),
    fetchIfWanted('reviews', getReviews),
    fetchIfWanted('claimEvidence', getClaimEvidence),
    fetchIfWanted('safety', getSafetyCompatible),
    fetchIfWanted('report', getReport),
  ]);
  return {
    run,
    hypotheses,
    evidence,
    matches,
    reviews,
    claimEvidence,
    safety,
    report,
  };
}

// Fetches a run's data, reporting a failure as a message rather than
// throwing, so the caller can decide whether the response is still wanted
// before it touches any state.
export async function fetchRunOutcome(
  id: string,
  keys?: ReadonlySet<RunDataKey>,
) {
  try {
    return {data: await fetchRunData(id, keys), error: null};
  } catch (err) {
    return {
      data: null,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

export type RunSnapshot = Awaited<ReturnType<typeof fetchRunData>>;
