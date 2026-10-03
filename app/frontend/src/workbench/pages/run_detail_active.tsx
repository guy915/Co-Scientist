import {useMemo, type ReactNode} from 'react';
import type {StreamEvent} from '@/hooks/use_run_stream';
import {formatDurationPhrase} from '@/lib/text';
import {useNowTick} from '@/workbench/hooks/timers';
import {RunExecutionProgress} from './chat_home_stage';
import {windowedActivityGroups} from './run_detail_activity_log';
import {ActivityLog} from './run_detail_activity_log';
import {type RunWithStreamState} from './run_detail_data';
import {
  SupervisorAllocationLedger,
  type AllocationLedgerState,
} from './run_detail_specifications';

// Cards shown in the activity log, not raw events -- see the comment on
// the useMemo below for why the window moved to that unit.
const ACTIVITY_WINDOW = 10;

/**
 * Live view of an in-flight run: the execution-progress flow, the headline
 * metrics, and the streaming activity timeline.
 */
interface ActiveRunViewProps {
  run: RunWithStreamState;
  events: StreamEvent[];
  evidenceCount: number;
  ideaCount: number;
  allocationLedger: AllocationLedgerState;
  outcomeStatus?: ReactNode;
}

// How long the run has been going, floored at zero to guard against clock
// skew between the client and the server's created_at. Elapsed time is a
// measurement rather than a projection, so unlike the estimate it replaced it
// is honest from the first second of the run.
function elapsedLabel(run: RunWithStreamState, nowSeconds: number): string {
  const elapsedSeconds = Math.max(0, nowSeconds - run.created_at);
  return formatDurationPhrase(elapsedSeconds, {subMinute: true});
}

// The headline metrics row.
function RunMetrics({
  elapsed,
  metrics,
}: {
  elapsed: string;
  metrics: [string, string][];
}) {
  // `my-0`: a <dl> carries a 1em user-agent block margin, which stacked on
  // top of the section's own 28px gap and separated these cards from the
  // progress header above and the activity log below by 44px instead — the
  // one place on the page whose vertical rhythm did not match the rest of it.
  return (
    <dl className="my-0 grid grid-cols-3 gap-3 max-[700px]:grid-cols-1">
      <RunMetric label="Time elapsed" value={elapsed} />
      {metrics.map(([label, value]) => (
        <RunMetric key={label} label={label} value={value} />
      ))}
    </dl>
  );
}

// The two cards beside the clock.
function headlineMetrics(props: ActiveRunViewProps): [string, string][] {
  return [
    ['Sources Analyzed', String(props.evidenceCount)],
    ['Ideas explored', String(props.ideaCount)],
  ];
}

export function ActiveRunView(props: ActiveRunViewProps) {
  const {run, events} = props;
  // Ticks every second so the elapsed clock advances visibly even while a slow
  // node holds the run without emitting a new event. The activity log's
  // relative timestamps ride the same clock.
  const nowSeconds = useNowTick(1000);
  const elapsed = elapsedLabel(run, nowSeconds);
  // Memoized on the events so the per-second clock ticks above don't re-scan
  // the whole event list just to advance timestamps. Windowed by GROUP, not
  // raw event, so a long run of one activity (a tournament's many matches)
  // collapses to one card instead of consuming the whole window itself --
  // see windowedActivityGroups for why that reversal matters.
  const activityGroups = useMemo(
    () =>
      windowedActivityGroups(
        events.filter(event => event.type !== 'status'),
        ACTIVITY_WINDOW,
      ),
    [events],
  );
  return (
    <main className="min-h-0 overflow-auto px-8 py-7 max-[700px]:px-4">
      {/* The section's three children are the progress header, the metric
          cards, and the activity log, so this gap *is* the space above and
          below the cards. 24px rather than 28: the cards sit 12px apart
          from each other, and a 28px moat around a 12px row read as three
          separate blocks instead of one metrics band. */}
      <section className="mx-auto grid w-full max-w-4xl gap-6">
        <div>
          <p className="text-sm font-medium text-cosci-blue">Executing</p>
          <h2 className="mt-1 text-2xl font-medium">Research in progress</h2>
          <RunExecutionProgress run={run} />
        </div>
        <RunMetrics elapsed={elapsed} metrics={headlineMetrics(props)} />
        <SupervisorAllocationLedger {...props.allocationLedger} />
        <ActivityLog
          groups={activityGroups}
          connection={run.stream_connection}
          nowSeconds={nowSeconds}
        />
        {props.outcomeStatus}
      </section>
    </main>
  );
}

function RunMetric({label, value}: {label: string; value: string}) {
  return (
    <div className="rounded-md bg-cosci-hover p-4">
      <dt className="text-xs text-cosci-muted">{label}</dt>
      {/* `ms-0`: a <dd>'s user-agent 40px inline indent pushed each value
          out of line with the label it belongs to. */}
      <dd className="mt-1 ms-0 text-xl font-medium">{value}</dd>
    </div>
  );
}
