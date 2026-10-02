import {useCallback, useEffect, useRef, useState} from 'react';
import type {
  ClaimEvidenceRow,
  Evidence,
  Hypothesis,
  MatchRow,
  Report,
  Review,
  RunWithSummary,
  SafetyDecision,
} from '@/api/runs';
import {useDebouncedCallback} from '@/workbench/hooks/use_debounced_callback';
import {useRunOutcomeCollection} from './run_detail_outcomes_data';
import {shouldRefreshOutcomes, type RunDataKey} from './run_detail_resources';
import {fetchRunOutcome, type RunSnapshot} from './run_detail_snapshot';

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

// Calls `setState` only when `value` was actually fetched (a selective
// refresh leaves the collections it did not request `undefined`).
function applyIfCurrent<T>(
  key: SnapshotResource,
  value: T | undefined,
  setState: (value: T) => void,
  owns: (key: SnapshotResource) => boolean,
) {
  if (value !== undefined && owns(key)) setState(value);
}

// Debounced, key-accumulating scheduler around `refresh`: the SSE stream
// replays the full history on mount and live runs emit rapid bursts, so
// per-event refetches collapse into one trailing call. Data keys accumulate
// in a ref across the debounce window (the underlying debounce keeps only
// the latest call's args), so a burst mixing event types still refetches
// every collection it touched. `cancelPending` drops a pending call without
// touching the accumulated keys (used when a full refresh makes them moot);
// `resetPending` also clears them (used on id change, so a stray key from
// the previous run doesn't leak into the next one's first batch).
function useDebouncedKeyedRefresh(
  refresh: (keys?: ReadonlySet<RunDataKey>) => Promise<void>,
) {
  const pendingRefreshKeys = useRef(new Set<RunDataKey>());
  const debouncedRefresh = useDebouncedCallback(() => {
    const keys = pendingRefreshKeys.current;
    pendingRefreshKeys.current = new Set();
    void refresh(keys);
  }, 600);

  const scheduleRefresh = useCallback(
    (keys: Iterable<RunDataKey>) => {
      for (const key of keys) pendingRefreshKeys.current.add(key);
      debouncedRefresh();
    },
    [debouncedRefresh],
  );

  const cancelPending = useCallback(() => {
    debouncedRefresh.cancel();
  }, [debouncedRefresh]);

  const resetPending = useCallback(() => {
    debouncedRefresh.cancel();
    pendingRefreshKeys.current = new Set();
  }, [debouncedRefresh]);

  return {scheduleRefresh, cancelPending, resetPending};
}

// The fetched run row and its collections, plus the applier refresh() uses
// to update only resources still owned by that request.
function useRunCollections() {
  const [run, setRun] = useState<RunWithSummary | null>(null);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [claimEvidence, setClaimEvidence] = useState<ClaimEvidenceRow[]>([]);
  const [safety, setSafety] = useState<SafetyDecision[]>([]);
  const [report, setReport] = useState<Report | null>(null);

  const applyFetched = useCallback(
    (data: RunSnapshot | null, owns: (key: SnapshotResource) => boolean) => {
      if (!data) return;
      applyIfCurrent('run', data.run, setRun, owns);
      applyIfCurrent('hypotheses', data.hypotheses, setHypotheses, owns);
      applyIfCurrent('evidence', data.evidence, setEvidence, owns);
      applyIfCurrent('matches', data.matches, setMatches, owns);
      applyIfCurrent('reviews', data.reviews, setReviews, owns);
      applyIfCurrent(
        'claimEvidence',
        data.claimEvidence,
        setClaimEvidence,
        owns,
      );
      applyIfCurrent('safety', data.safety, setSafety, owns);
      applyIfCurrent('report', data.report, setReport, owns);
    },
    [],
  );

  // Clears every collection back to its empty value. The run-detail route
  // element is mounted once for /runs/:id/:tab, so an id change is a new run
  // in the same component instance: without this, the previous run's
  // hypotheses, report and status keep rendering as if they were this run's
  // until the new fetch lands.
  const reset = useCallback(() => {
    setRun(null);
    setHypotheses([]);
    setEvidence([]);
    setMatches([]);
    setReviews([]);
    setClaimEvidence([]);
    setSafety([]);
    setReport(null);
  }, []);

  return {
    run,
    hypotheses,
    evidence,
    matches,
    reviews,
    claimEvidence,
    safety,
    report,
    applyFetched,
    reset,
  };
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
