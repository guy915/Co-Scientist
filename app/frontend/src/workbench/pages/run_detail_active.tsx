import type {StreamEvent} from '@/hooks/use_run_stream';
import {formatDurationPhrase} from '@/lib/text';
import {useNowTick} from '@/workbench/hooks/timers';
import {useMemo} from 'react';
import {RunExecutionProgress} from './chat_home_stage';
import {ActivityLog, windowedActivityGroups} from './run_detail_activity_log';
import {type RunWithStreamState} from './run_detail_data';

const ACTIVITY_WINDOW = 10;

interface ActiveRunViewProps {
  run: RunWithStreamState;
  events: StreamEvent[];
  evidenceCount: number;
  ideaCount: number;
}

// Floor elapsed time at zero to tolerate client/server clock skew.
function elapsedLabel(run: RunWithStreamState, nowSeconds: number): string {
  const elapsedSeconds = Math.max(0, nowSeconds - run.created_at);
  return formatDurationPhrase(elapsedSeconds, {subMinute: true});
}

function RunMetrics({
  elapsed,
  metrics,
}: {
  elapsed: string;
  metrics: [string, string][];
}) {
  // Remove the default dl margin so it does not add to the section gap.
  return (
    <dl className="my-0 grid grid-cols-3 gap-3 max-[700px]:grid-cols-1">
      <RunMetric label="Time elapsed" value={elapsed} />
      {metrics.map(([label, value]) => (
        <RunMetric key={label} label={label} value={value} />
      ))}
    </dl>
  );
}

function headlineMetrics(props: ActiveRunViewProps): [string, string][] {
  return [
    ['Sources Analyzed', String(props.evidenceCount)],
    ['Ideas explored', String(props.ideaCount)],
  ];
}

export function ActiveRunView(props: ActiveRunViewProps) {
  const {run, events} = props;
  const nowSeconds = useNowTick(1000);
  const elapsed = elapsedLabel(run, nowSeconds);
  // Window by activity group, not raw event, so tournament bursts cannot
  // consume the visible history.
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
        <ActivityLog
          groups={activityGroups}
          connection={run.stream_connection}
          nowSeconds={nowSeconds}
        />
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
