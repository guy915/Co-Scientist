import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
  runGoal,
  type RunWithSummary,
  getSupervisorPlan,
  type SupervisorPlanResponse,
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
  type SafetyDecision,
} from '@/api/runs';
import {
  type StreamConnectionState,
  useRunStream,
  type StreamEvent,
} from '@/hooks/use_run_stream';
import {HEADER_TITLE_EVENT} from '../dom_events';
import {useResetTimer} from '@/workbench/hooks/timers';

// Carry stream transport state with the run so reconnecting cannot look
// healthy; missing state is not evidence of a drop.
export type RunWithStreamState = RunWithSummary & {
  stream_connection?: StreamConnectionState;
};

function useRunEventStream(
  id: string | undefined,
  onDataEvents: (keys: Iterable<RunDataKey>) => void,
  onSupervisorPlanEvent: () => void,
  onTerminal: () => void,
) {
  const {events, terminal, connection} = useRunStream(id ?? null);
  const previousConnection = useRef({id, connection});

  // A checkpoint can persist before its completion event; refresh the optional
  // ledger on open and reconnect.
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

  // Scan every coalesced event, not only the tail, so a final status cannot
  // hide an earlier data update.
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

  // Refresh immediately on stream end so a pending debounce cannot leave
  // terminal state stale.
  useEffect(() => {
    if (!terminal) return;
    onTerminal();
  }, [terminal, onTerminal]);

  return {events, terminal, connection};
}

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

function useRunDerivedState(run: RunWithSummary | null, terminal: boolean) {
  const [toast, setToast] = useState<string | null>(null);
  useEffect(() => {
    if (!terminal || !run) return;
    const toastMessage = runEndToast(run);
    if (toastMessage) setToast(toastMessage);
  }, [terminal, run]);

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

export function useRunDetailData(id: string | undefined) {
  const {scheduleRefresh, ...data} = useRunDetailCollections(id);
  const supervisorPlan = useRunSupervisorPlan(id);
  const onTerminal = useCallback(() => {
    data.refreshNow();
    void supervisorPlan.refresh();
  }, [data.refreshNow, supervisorPlan.refresh]);
  const {events, terminal, connection} = useRunEventStream(
    id,
    scheduleRefresh,
    supervisorPlan.refresh,
    onTerminal,
  );
  const {toast, title} = useRunDerivedState(data.run, terminal);

  const run = useMemo<RunWithStreamState | null>(
    () =>
      data.run === null ? null : {...data.run, stream_connection: connection},
    [data.run, connection],
  );

  return {
    ...data,
    run,
    supervisorPlan: supervisorPlan.state,
    toast,
    title,
    refreshSupervisorPlan: supervisorPlan.refresh,
    events,
  };
}

export interface SupervisorPlanLoadState {
  response: SupervisorPlanResponse | null;
  loading: boolean;
  error: string | null;
}

type RunTaggedPlanState = SupervisorPlanLoadState & {
  runId: string | undefined;
};

function isCurrentRequest(
  shownId: string | undefined,
  currentRequest: number,
  id: string,
  request: number,
): boolean {
  return shownId === id && currentRequest === request;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function useRunSupervisorPlan(id: string | undefined) {
  const [state, setState] = useState<RunTaggedPlanState>({
    runId: id,
    response: null,
    loading: Boolean(id),
    error: null,
  });
  const shownId = useRef(id);
  const requestId = useRef(0);

  const refresh = useCallback(async () => {
    if (!id) return;
    const request = ++requestId.current;
    setState(current => ({...current, loading: true, error: null}));
    try {
      const response = await getSupervisorPlan(id);
      if (!isCurrentRequest(shownId.current, requestId.current, id, request))
        return;
      setState({runId: id, response, loading: false, error: null});
    } catch (error) {
      if (!isCurrentRequest(shownId.current, requestId.current, id, request))
        return;
      setState(current => ({
        ...current,
        loading: false,
        error: errorMessage(error),
      }));
    }
  }, [id]);

  useEffect(() => {
    shownId.current = id;
    requestId.current += 1;
    setState({runId: id, response: null, loading: Boolean(id), error: null});
    void refresh();
  }, [id, refresh]);

  const currentState: SupervisorPlanLoadState =
    state.runId === id
      ? state
      : {response: null, loading: Boolean(id), error: null};
  return {state: currentState, refresh};
}

export function runFailureGuidance(
  failureKind: string | null | undefined,
): {message: string; toast: string} | null {
  switch (failureKind) {
    case 'llm_call_budget_exceeded':
      return {
        message:
          'The run reached its configured model-call limit before it completed. Start a new run with a narrower research goal.',
        toast: 'Run failed. See the suggested next step below.',
      };
    case 'llm_timeout':
      return {
        message:
          'The model provider did not respond within the request timeout. Try the research again later.',
        toast: 'Run failed. See the suggested next step below.',
      };
    case 'llm_timeout_unknown':
      return {
        message:
          'The provider may have accepted the request; acceptance and any charge are unconfirmed. The run was not retried automatically. Restarting or resuming may repeat provider work.',
        toast: 'Run failed. See the suggested next step below.',
      };
    default:
      return null;
  }
}

export type RunDataKey =
  | 'hypotheses'
  | 'evidence'
  | 'matches'
  | 'reviews'
  | 'claimEvidence'
  | 'outcomes'
  | 'safety'
  | 'report';

// Terminal full refresh covers artifacts persisted only during finalize.
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

async function fetchRunData(id: string, keys?: ReadonlySet<RunDataKey>) {
  const fetchIfWanted = <T>(
    key: RunDataKey,
    fetcher: (id: string) => Promise<T>,
  ): Promise<T> | undefined =>
    !keys || keys.has(key) ? fetcher(id) : undefined;
  // Older backends may lack safety audit during rolling upgrades; the rest of
  // the report must stay readable.
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
      // Disjoint requests can both land; each overlapping resource belongs to
      // its latest read.
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

export function useRunDetailCollections(id: string | undefined) {
  const {applyFetched, reset, ...collections} = useRunCollections();
  const outcomeCollection = useRunOutcomeCollection();
  // Match settled data to the current run id before effects execute, or
  // navigation flashes the previous report.
  const [settled, setSettled] = useState<{
    id: string;
    error: string | null;
  } | null>(null);
  const current = settled?.id === id ? settled : null;
  const loaded = current !== null;
  const error = current?.error ?? null;
  const shownId = useRef<string | undefined>(undefined);
  const requestSequence = useRef(0);
  const resourceOwners = useRef(new Map<SnapshotResource, number>());

  const refresh = useCallback(
    async (keys?: ReadonlySet<RunDataKey>) => {
      if (!isShownRun(id, shownId.current)) return;
      const request = ++requestSequence.current;
      // Guard requests per resource: a later review fetch must not discard an
      // earlier generation fetch.
      claimSnapshotResources(resourceOwners.current, request, keys);
      const owns = (resource: SnapshotResource) =>
        resourceOwners.current.get(resource) === request;
      if (shouldRefreshOutcomes(keys)) void outcomeCollection.refresh(id);
      const outcome = await fetchRunOutcome(id, keys);
      // Reject old-run responses after navigation so they cannot repopulate
      // the new run's view.
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
