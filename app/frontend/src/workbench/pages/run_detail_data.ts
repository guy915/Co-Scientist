import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
  type ClaimEvidenceRow,
  type Evidence,
  getClaimEvidence,
  getEvidence,
  getHypotheses,
  getMatches,
  getReport,
  getReviews,
  getRun,
  getSafety,
  type Hypothesis,
  type MatchRow,
  type Report,
  type Review,
  runGoal,
  type RunWithSummary,
  type SafetyDecision,
} from '@/api/runs';
import {useDebouncedCallback} from '@/workbench/hooks/use_debounced_callback';
import {runFailureGuidance} from './run_failure_guidance';
import {
  type StreamConnectionState,
  type StreamEvent,
  useRunStream,
} from '@/hooks/use_run_stream';
import {HEADER_TITLE_EVENT} from '../dom_events';
import {useRunSupervisorPlan} from './run_detail_supervisor_plan_data';

/**
 * The fetched run row plus the live transport state of its event stream.
 * The connection state rides the row because the live-run view receives
 * only the row and the timeline: a dropped or reconnecting stream must
 * stay visible there instead of reading as healthy. Optional so consumers
 * treat a missing state (e.g. a test double with no transport field) as
 * "no signal", not as a drop.
 */
export type RunWithStreamState = RunWithSummary & {
  stream_connection?: StreamConnectionState;
};

type RunDataKey =
  | 'hypotheses'
  | 'evidence'
  | 'matches'
  | 'reviews'
  | 'claimEvidence'
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
  proximity: ['hypotheses'],
  ranking: ['hypotheses', 'matches'],
  evolve: ['hypotheses', 'claimEvidence'],
  report: ['report'],
};

// Collects the RunDataKey set a batch of newly-arrived events touches
// (multiple event types can map to the same key; see EVENT_DATA_KEYS).
function dataKeysFromEvents(events: readonly StreamEvent[]): Set<RunDataKey> {
  const keys = new Set<RunDataKey>();
  for (const event of events) {
    for (const key of EVENT_DATA_KEYS[event.type] ?? []) keys.add(key);
  }
  return keys;
}

function hasSupervisorPlanEvent(events: readonly StreamEvent[]): boolean {
  return events.some(
    event =>
      event.type === 'scientific_task' && event.payload.task === 'orchestrator',
  );
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

// Calls `setState` only when `value` was actually fetched (a selective
// refresh leaves the collections it did not request `undefined`).
function applyIfFetched<T>(value: T | undefined, setState: (value: T) => void) {
  if (value !== undefined) setState(value);
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

// Fetches and keeps in sync the run row plus its hypotheses/evidence/
// matches/reviews/report collections. `scheduleRefresh` is a debounced
// partial refetch keyed by collection (used by the SSE event stream below),
// and `refreshNow` is an immediate cancel-and-refetch (used on stream
// termination).
// The fetched run row and its collections, plus the applier refresh() uses
// to update only the collections that were actually fetched.
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
    (data: Awaited<ReturnType<typeof fetchRunData>>) => {
      setRun(data.run);
      applyIfFetched(data.hypotheses, setHypotheses);
      applyIfFetched(data.evidence, setEvidence);
      applyIfFetched(data.matches, setMatches);
      applyIfFetched(data.reviews, setReviews);
      applyIfFetched(data.claimEvidence, setClaimEvidence);
      applyIfFetched(data.safety, setSafety);
      applyIfFetched(data.report, setReport);
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

function useRunFetch(id: string | undefined) {
  const {applyFetched, reset, ...collections} = useRunCollections();
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
  const shownId = useRef(id);

  // With no key set, everything is refetched (initial load, terminal drain).
  // With one, only the run row plus the named collections are, so a mid-run
  // event burst does not fan out to all six endpoints indiscriminately.
  const refresh = useCallback(
    async (keys?: ReadonlySet<RunDataKey>) => {
      if (!id) return;
      const outcome = await fetchRunOutcome(id, keys);
      // Drop a response for a run the page has since navigated away from: the
      // previous run's in-flight fetch can land after the switch, and applying
      // it would repopulate the new run's view with the old run's data.
      if (shownId.current !== id) return;
      if (outcome.data) applyFetched(outcome.data);
      setSettled({id, error: outcome.error});
    },
    [id, applyFetched],
  );

  const {scheduleRefresh, cancelPending, resetPending} =
    useDebouncedKeyedRefresh(refresh);

  const refreshNow = useCallback(() => {
    cancelPending();
    void refresh();
  }, [refresh, cancelPending]);

  // Initial load (and reload when the run id changes) stays immediate. Only
  // an id change resets: `refresh` is stable for a given id, so the SSE-driven
  // partial refetches below never clear what is on screen -- they update it.
  useEffect(() => {
    shownId.current = id;
    resetPending();
    reset();
    void refresh();
  }, [id, refresh, resetPending, reset]);

  return {
    ...collections,
    error,
    loaded,
    scheduleRefresh,
    refreshNow,
  };
}

// Wires the live SSE event stream for a run (replayed from seq=0 on mount):
// calls `onDataEvents` with the set of collections a coalesced batch of
// events can change, and `onTerminal` once the stream reaches its terminal
// sentinel. Returns `terminal` and the stream's transport `connection` so
// callers can derive their own state from them.
function useRunEventStream(
  id: string | undefined,
  onDataEvents: (keys: Iterable<RunDataKey>) => void,
  onSupervisorPlanEvent: () => void,
  onTerminal: () => void,
) {
  const {events, terminal, connection} = useRunStream(id ?? null);
  const previousConnection = useRef({id, connection});

  // A durable checkpoint can persist the ledger before its completion event
  // is appended. Stream replay can miss that gap, so refresh the optional
  // ledger once when the transport first opens or reconnects.
  useEffect(() => {
    const previous = previousConnection.current;
    previousConnection.current = {id, connection};
    if (
      previous.id === id &&
      previous.connection !== 'open' &&
      connection === 'open'
    ) {
      onSupervisorPlanEvent();
    }
  }, [connection, id, onSupervisorPlanEvent]);

  // The stream delivers events in coalesced batches, so scan the whole newly
  // appended slice for data events rather than only the batch tail: a batch
  // that ends in a 'status' event still warrants a refetch if it carried a
  // node event earlier. The processed-count ref resets naturally when the
  // hook clears events on a run change (length drops back toward zero).
  const processedEventCount = useRef(0);
  useEffect(() => {
    if (events.length < processedEventCount.current) {
      processedEventCount.current = 0;
    }
    const fresh = events.slice(processedEventCount.current);
    processedEventCount.current = events.length;
    const data = fresh.filter(event => event.type !== 'status');
    if (data.length === 0) return;
    const keys = dataKeysFromEvents(data);
    if (keys.size > 0) onDataEvents(keys);
    if (hasSupervisorPlanEvent(data)) onSupervisorPlanEvent();
  }, [events, onDataEvents, onSupervisorPlanEvent]);

  // On stream end, refetch immediately so a pending debounce cannot leave the
  // completed state stale.
  useEffect(() => {
    if (!terminal) return;
    onTerminal();
  }, [terminal, onTerminal]);

  return {events, terminal, connection};
}

// Toast message for a run that just reached a failed/blocked terminal state,
// or null when the run doesn't warrant one.
function failedRunToast(run: RunWithSummary): string {
  const guidance = runFailureGuidance(run.failure_kind);
  if (guidance) return guidance.toast;
  return `Run failed${run.error ? `: ${run.error}` : ''}`;
}

function runEndToast(run: RunWithSummary): string | null {
  if (run.status === 'failed') return failedRunToast(run);
  if (run.status === 'blocked') {
    return `Run blocked${run.error ? `: ${run.error}` : ''}`;
  }
  return null;
}

// Derives the toast (shown when a run ends failed/blocked) and the display
// title (curated domain override, else the goal) from the fetched run row,
// and dispatches the title to the shell header.
function useRunDerivedState(run: RunWithSummary | null, terminal: boolean) {
  const [toast, setToast] = useState<string | null>(null);
  useEffect(() => {
    if (!terminal || !run) return;
    const toastMessage = runEndToast(run);
    if (toastMessage) setToast(toastMessage);
  }, [terminal, run]);

  // Full display title: the model-generated run title when present (the same
  // value shown on the recents cards and sidebar chats), else the research
  // goal. Shared by the shell-header dispatch and the titlebar; each host
  // truncates to its own available width via TruncatedLabel.
  const title = useMemo(() => {
    if (!run) return 'Goal report';
    return run.title?.trim() || runGoal(run);
  }, [run]);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent(HEADER_TITLE_EVENT, {detail: title}));
    return () => {
      window.dispatchEvent(new CustomEvent(HEADER_TITLE_EVENT, {detail: ''}));
    };
  }, [title]);

  return {toast, title};
}

/**
 * Fetches and keeps in sync all data backing the goal-report surface: the run
 * row plus its hypotheses/evidence/matches/reviews/report collections, wired
 * to the live SSE event stream so mid-run updates refetch just the
 * collections a given event type can change. Also derives the display title
 * and dispatches it to the shell header, and raises a toast if the run ends
 * failed/blocked. The returned run row carries the stream's transport state
 * (see RunWithStreamState) so the live-run view can surface a dropped or
 * reconnecting connection instead of reading as healthy.
 */
export function useRunDetailData(id: string | undefined) {
  const data = useRunFetch(id);
  const supervisorPlan = useRunSupervisorPlan(id);
  const onTerminal = useCallback(() => {
    data.refreshNow();
    void supervisorPlan.refresh();
  }, [data.refreshNow, supervisorPlan.refresh]);
  const {events, terminal, connection} = useRunEventStream(
    id,
    data.scheduleRefresh,
    supervisorPlan.refresh,
    onTerminal,
  );
  const {toast, title} = useRunDerivedState(data.run, terminal);

  // Memoized so the augmented row keeps a stable identity between refetches
  // and connection changes, the way the bare fetched row did.
  const run = useMemo<RunWithStreamState | null>(
    () =>
      data.run === null ? null : {...data.run, stream_connection: connection},
    [data.run, connection],
  );

  return {
    run,
    hypotheses: data.hypotheses,
    evidence: data.evidence,
    matches: data.matches,
    reviews: data.reviews,
    claimEvidence: data.claimEvidence,
    safety: data.safety,
    supervisorPlan: supervisorPlan.state,
    report: data.report,
    error: data.error,
    loaded: data.loaded,
    toast,
    title,
    refreshNow: data.refreshNow,
    refreshSupervisorPlan: supervisorPlan.refresh,
    events,
  };
}
