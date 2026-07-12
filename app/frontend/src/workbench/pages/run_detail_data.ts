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
import {useDebouncedCallback} from '@/hooks/use_debounced_callback';
import {type StreamEvent, useRunStream} from '@/hooks/use_run_stream';

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
function useRunFetch(id: string | undefined) {
  // --- Fetched run data (populated by refresh(), see below) ---
  const [run, setRun] = useState<RunWithSummary | null>(null);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [claimEvidence, setClaimEvidence] = useState<ClaimEvidenceRow[]>([]);
  const [safety, setSafety] = useState<SafetyDecision[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // With no key set, everything is refetched (initial load, terminal drain).
  // With one, only the run row plus the named collections are, so a mid-run
  // event burst does not fan out to all six endpoints indiscriminately.
  const refresh = useCallback(
    async (keys?: ReadonlySet<RunDataKey>) => {
      if (!id) return;
      try {
        const data = await fetchRunData(id, keys);
        setRun(data.run);
        applyIfFetched(data.hypotheses, setHypotheses);
        applyIfFetched(data.evidence, setEvidence);
        applyIfFetched(data.matches, setMatches);
        applyIfFetched(data.reviews, setReviews);
        applyIfFetched(data.claimEvidence, setClaimEvidence);
        applyIfFetched(data.safety, setSafety);
        applyIfFetched(data.report, setReport);
        setLoaded(true);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setLoaded(true);
      }
    },
    [id],
  );

  const {scheduleRefresh, cancelPending, resetPending} =
    useDebouncedKeyedRefresh(refresh);

  const refreshNow = useCallback(() => {
    cancelPending();
    void refresh();
  }, [refresh, cancelPending]);

  // Initial load (and reload when the run id changes) stays immediate.
  useEffect(() => {
    resetPending();
    void refresh();
  }, [refresh, resetPending]);

  return {
    run,
    hypotheses,
    evidence,
    matches,
    reviews,
    claimEvidence,
    safety,
    report,
    error,
    loaded,
    scheduleRefresh,
    refreshNow,
  };
}

// Wires the live SSE event stream for a run (replayed from seq=0 on mount):
// calls `onDataEvents` with the set of collections a coalesced batch of
// events can change, and `onTerminal` once the stream reaches its terminal
// sentinel. Returns `terminal` so callers can derive their own state from it.
function useRunEventStream(
  id: string | undefined,
  onDataEvents: (keys: Iterable<RunDataKey>) => void,
  onTerminal: () => void,
) {
  const {events, terminal} = useRunStream(id ?? null);

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
    onDataEvents(dataKeysFromEvents(data));
  }, [events, onDataEvents]);

  // On stream end, refetch immediately so a pending debounce cannot leave the
  // completed state stale.
  useEffect(() => {
    if (!terminal) return;
    onTerminal();
  }, [terminal, onTerminal]);

  return {terminal};
}

// Toast message for a run that just reached a failed/blocked terminal state,
// or null when the run doesn't warrant one.
function runEndToast(run: RunWithSummary): string | null {
  if (run.status !== 'failed' && run.status !== 'blocked') return null;
  return `Run ${run.status}${run.error ? `: ${run.error}` : ''}`;
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

  // Full display title (the run's goal). Shared by the shell-header dispatch
  // and the titlebar; each host truncates to its own available width via
  // TruncatedLabel rather than being pre-shortened.
  const title = useMemo(() => {
    if (!run) return 'Goal report';
    return runGoal(run);
  }, [run]);

  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent('cosci-header-title', {detail: title}),
    );
    return () => {
      window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: ''}));
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
 * failed/blocked.
 */
export function useRunDetailData(id: string | undefined) {
  const data = useRunFetch(id);
  const {terminal} = useRunEventStream(
    id,
    data.scheduleRefresh,
    data.refreshNow,
  );
  const {toast, title} = useRunDerivedState(data.run, terminal);

  return {
    run: data.run,
    hypotheses: data.hypotheses,
    evidence: data.evidence,
    matches: data.matches,
    reviews: data.reviews,
    claimEvidence: data.claimEvidence,
    safety: data.safety,
    report: data.report,
    error: data.error,
    loaded: data.loaded,
    toast,
    title,
    refreshNow: data.refreshNow,
  };
}
