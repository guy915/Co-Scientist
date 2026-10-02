import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {runGoal, type RunWithSummary} from '@/api/runs';
import {type StreamConnectionState, useRunStream} from '@/hooks/use_run_stream';
import {HEADER_TITLE_EVENT} from '../dom_events';
import {runFailureGuidance} from './run_failure_guidance';
import {
  useRunDetailCollections,
  dataKeysFromEvents,
  hasSupervisorPlanEvent,
  type RunDataKey,
} from './run_detail_collections';
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

  // Memoized so the augmented row keeps a stable identity between refetches
  // and connection changes, the way the bare fetched row did.
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
