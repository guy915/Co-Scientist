import {useCallback, useEffect, useRef, useState} from 'react';
import {
  getClaimEvidence,
  getEvidence,
  getHypotheses,
  getHypothesisOutcomes,
  getMatches,
  getReport,
  getReviews,
  getRun,
  getSafety,
  type ClaimEvidenceRow,
  type Evidence,
  type Hypothesis,
  type HypothesisOutcome,
  type MatchRow,
  type Report,
  type Review,
  type RunWithSummary,
  type SafetyDecision,
} from '@/api/runs';
import type {StreamEvent} from '@/hooks/use_run_stream';
import {useResetTimer} from '@/workbench/hooks/use_reset_timer';

export type RunDataKey =
  | 'hypotheses'
  | 'evidence'
  | 'matches'
  | 'reviews'
  | 'claimEvidence'
  | 'outcomes'
  | 'safety'
  | 'report';

// Which fetched collections each canonical event type can change mid-run.
// Event types not listed (supervisor.plan, research_overview, safety.*, ...)
// only affect the run row itself, which every refresh re-reads; the terminal
// full refresh is the safety net for anything persisted only at finalize.
const EVENT_DATA_KEYS: Record<string, readonly RunDataKey[]> = {
  literature_review: ['evidence'],
  generate: ['hypotheses'],
  reflection: ['reviews'],
  review: ['reviews'],
  meta_review: ['reviews'],
  deep_verification: ['reviews'],
  'citation.grounding': ['claimEvidence'],
  'safety.intake': ['safety'],
  'safety.final': ['safety'],
  'scientist.hypothesis': ['hypotheses', 'safety'],
  'scientist.review': ['reviews'],
  'scientist.outcome': ['outcomes'],
  proximity: ['hypotheses'],
  ranking: ['hypotheses', 'matches'],
  evolve: ['hypotheses', 'claimEvidence'],
  report: ['report'],
};

// Collects the RunDataKey set a batch of newly-arrived events touches
// (multiple event types can map to the same key; see EVENT_DATA_KEYS).
export function dataKeysFromEvents(
  events: readonly StreamEvent[],
): Set<RunDataKey> {
  const keys = new Set<RunDataKey>();
  for (const event of events) {
    for (const key of EVENT_DATA_KEYS[event.type] ?? []) keys.add(key);
  }
  return keys;
}

export function hasSupervisorPlanEvent(
  events: readonly StreamEvent[],
): boolean {
  return events.some(
    event =>
      event.type === 'scientific_task' && event.payload.task === 'orchestrator',
  );
}

function shouldRefreshOutcomes(keys?: ReadonlySet<RunDataKey>): boolean {
  return keys === undefined || keys.has('outcomes');
}

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
async function fetchRunOutcome(id: string, keys?: ReadonlySet<RunDataKey>) {
  try {
    return {data: await fetchRunData(id, keys), error: null};
  } catch (err) {
    return {
      data: null,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

type RunSnapshot = Awaited<ReturnType<typeof fetchRunData>>;

type SnapshotResource = keyof RunSnapshot;

const SNAPSHOT_RESOURCES: readonly SnapshotResource[] = [
  'run',
  'hypotheses',
  'evidence',
  'matches',
  'reviews',
  'claimEvidence',
  'safety',
  'report',
];

function claimSnapshotResources(
  owners: Map<SnapshotResource, number>,
  request: number,
  keys: ReadonlySet<RunDataKey> | undefined,
) {
  for (const resource of SNAPSHOT_RESOURCES) {
    if (resource === 'run' || !keys || keys.has(resource)) {
      owners.set(resource, request);
    }
  }
}

function isShownRun(
  id: string | undefined,
  shownId: string | undefined,
): id is string {
  return id !== undefined && shownId === id;
}

// Merge every collection touched during one trailing debounce window.
function useDebouncedKeyedRefresh(
  refresh: (keys?: ReadonlySet<RunDataKey>) => Promise<void>,
) {
  const pending = useRef(new Set<RunDataKey>());
  const refreshRef = useRef(refresh);
  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);
  const {schedule, cancel} = useResetTimer();
  const scheduleRefresh = useCallback(
    (keys: Iterable<RunDataKey>) => {
      for (const key of keys) pending.current.add(key);
      schedule(() => {
        const keys = pending.current;
        pending.current = new Set();
        void refreshRef.current(keys);
      }, 600);
    },
    [schedule],
  );
  const resetPending = useCallback(() => {
    cancel();
    pending.current = new Set();
  }, [cancel]);
  return {scheduleRefresh, cancelPending: cancel, resetPending};
}

interface CollectionsState {
  run: RunWithSummary | null;
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  matches: MatchRow[];
  reviews: Review[];
  claimEvidence: ClaimEvidenceRow[];
  safety: SafetyDecision[];
  report: Report | null;
}

const EMPTY_COLLECTIONS: CollectionsState = {
  run: null,
  hypotheses: [],
  evidence: [],
  matches: [],
  reviews: [],
  claimEvidence: [],
  safety: [],
  report: null,
};

function useRunCollections() {
  const [collections, setCollections] = useState(EMPTY_COLLECTIONS);
  const applyFetched = useCallback(
    (data: RunSnapshot | null, owns: (key: SnapshotResource) => boolean) => {
      if (!data) return;
      // Disjoint requests may both land; each key belongs to its latest read.
      const updates = Object.fromEntries(
        Object.entries(data).filter(
          ([key, value]) =>
            value !== undefined && owns(key as SnapshotResource),
        ),
      );
      setCollections(current => ({...current, ...updates}));
    },
    [],
  );
  const reset = useCallback(() => setCollections(EMPTY_COLLECTIONS), []);
  return {...collections, applyFetched, reset};
}

/** Owns selective refreshes, collection state and the run-detail load lifecycle. */
export function useRunDetailCollections(id: string | undefined) {
  const {applyFetched, reset, ...collections} = useRunCollections();
  const outcomeCollection = useRunOutcomeCollection();
  // Which run the settled state describes, rather than a bare loaded flag and
  // a bare error. The reset below runs in an effect, i.e. after the render
  // that follows an id change -- so on that render bare values still describe
  // the *previous* run, and the page paints a frame of the last run's report
  // (tab nav, ideas and all) before the effect clears them. Matching on the
  // current id is correct during that render, with no effect ordering to
  // depend on.
  const [settled, setSettled] = useState<{
    id: string;
    error: string | null;
  } | null>(null);
  const current = settled?.id === id ? settled : null;
  const loaded = current !== null;
  const error = current?.error ?? null;
  // The run the page is currently showing, so a response can be checked
  // against it after the await (see refresh below).
  const shownId = useRef<string | undefined>(undefined);
  const requestSequence = useRef(0);
  const resourceOwners = useRef(new Map<SnapshotResource, number>());

  // With no key set, everything is refetched (initial load, terminal drain).
  // With one, only the run row plus the named collections are, so a mid-run
  // event burst does not fan out to all six endpoints indiscriminately.
  const refresh = useCallback(
    async (keys?: ReadonlySet<RunDataKey>) => {
      if (!isShownRun(id, shownId.current)) return;
      const request = ++requestSequence.current;
      // A single latest-request guard would drop an older generation read
      // merely because a review read started after it. Track each resource:
      // disjoint collections can both land, while their shared run row and
      // any overlapping collections always belong to the newer request.
      claimSnapshotResources(resourceOwners.current, request, keys);
      const owns = (resource: SnapshotResource) =>
        resourceOwners.current.get(resource) === request;
      if (shouldRefreshOutcomes(keys)) void outcomeCollection.refresh(id);
      const outcome = await fetchRunOutcome(id, keys);
      // Drop a response for a run the page has since navigated away from: the
      // previous run's in-flight fetch can land after the switch, and applying
      // it would repopulate the new run's view with the old run's data.
      if (!isShownRun(id, shownId.current)) return;
      applyFetched(outcome.data, owns);
      if (owns('run')) setSettled({id, error: outcome.error});
    },
    [id, applyFetched, outcomeCollection.refresh],
  );

  const {scheduleRefresh, cancelPending, resetPending} =
    useDebouncedKeyedRefresh(refresh);

  const refreshNow = useCallback(() => {
    cancelPending();
    void refresh();
  }, [refresh, cancelPending]);

  const refreshOutcomesNow = useCallback(async () => {
    if (shownId.current !== id) return;
    await outcomeCollection.refresh(id);
  }, [id, outcomeCollection.refresh]);

  // Initial load (and reload when the run id changes) stays immediate. Only
  // an id change resets: `refresh` is stable for a given id, so the SSE-driven
  // partial refetches below never clear what is on screen -- they update it.
  useEffect(() => {
    shownId.current = id;
    resetPending();
    reset();
    outcomeCollection.reset(id);
    void refresh();
    return () => {
      shownId.current = undefined;
      resourceOwners.current.clear();
      resetPending();
      outcomeCollection.reset(undefined);
    };
  }, [id, refresh, resetPending, reset, outcomeCollection.reset]);

  return {
    ...collections,
    outcomes: outcomeCollection.outcomes,
    outcomesLoading: outcomeCollection.loading,
    outcomesError: outcomeCollection.error,
    error,
    loaded,
    scheduleRefresh,
    refreshNow,
    refreshOutcomes: refreshOutcomesNow,
  };
}

async function fetchOutcomes(id: string) {
  try {
    return {data: await getHypothesisOutcomes(id), error: null};
  } catch (err) {
    return {
      data: null,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

/** Keeps the append-only outcome collection isolated from report fetch errors. */
export function useRunOutcomeCollection() {
  const [outcomes, setOutcomes] = useState<HypothesisOutcome[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const shownId = useRef<string | undefined>(undefined);
  const requestGeneration = useRef(0);

  const reset = useCallback((id: string | undefined) => {
    shownId.current = id;
    requestGeneration.current += 1;
    setOutcomes([]);
    setLoading(true);
    setError(null);
  }, []);

  const refresh = useCallback(async (id: string | undefined) => {
    if (!id) return;
    const generation = ++requestGeneration.current;
    setLoading(true);
    const result = await fetchOutcomes(id);
    if (shownId.current !== id || requestGeneration.current !== generation) {
      return;
    }
    if (result.data) setOutcomes(result.data);
    setError(result.error);
    setLoading(false);
  }, []);

  return {outcomes, loading, error, reset, refresh};
}
