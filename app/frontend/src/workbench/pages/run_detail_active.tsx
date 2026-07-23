import {useEffect, useMemo, useState} from 'react';
import {type RunWithSummary} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import type {StreamEvent} from '@/hooks/use_run_stream';
import {joinClasses} from '../classes';
import {RunExecutionProgress} from './home_recents_run_steps';

const IDLE_NOTE_CLASSES =
  'mt-4 flex items-center gap-3 rounded-md bg-cosci-hover px-4 py-3.5';
const IDLE_DOT_CLASSES =
  'size-2 shrink-0 animate-pulse rounded-full bg-cosci-muted';
const PULSE_RING_CLASSES =
  'absolute inline-flex size-full animate-ping rounded-full bg-th-primary';
const PULSE_DOT_CLASSES =
  'relative inline-flex size-2.5 rounded-full bg-th-primary';
const TIMELINE_RAIL_CLASSES =
  'absolute left-[1.0625rem] top-[2.375rem] bottom-1 w-px bg-cosci-border';
const TIMELINE_ROW_CLASSES =
  'flex min-h-[2.125rem] items-center justify-between gap-3';

/**
 * Live view of an in-flight run: the execution-progress flow, the headline
 * metrics, and the streaming activity timeline.
 */
interface ActiveRunViewProps {
  run: RunWithSummary;
  events: StreamEvent[];
  evidenceCount: number;
  ideaCount: number;
}

// The determinate progress fraction, only once it is both reported and
// meaningfully positive (a zero or negative fraction can't project a rate).
function meaningfulFraction(run: RunWithSummary): number | null {
  const progress = run.execution_progress;
  if (!progress?.determinate) return null;
  const fraction = progress.fraction;
  if (!fraction || fraction <= 0) return null;
  return fraction;
}

// Estimated seconds left, from the determinate progress fraction; null while
// the estimate is not yet meaningful.
function estimateRemainingSeconds(
  run: RunWithSummary,
  nowSeconds: number,
): number | null {
  const fraction = meaningfulFraction(run);
  if (fraction === null) return null;
  const elapsedSeconds = Math.max(0, Math.round(nowSeconds - run.created_at));
  return Math.max(0, Math.round((elapsedSeconds * (1 - fraction)) / fraction));
}

// The headline metrics row: time remaining, sources, and idea count.
function RunMetrics({
  remainingSeconds,
  evidenceCount,
  ideaCount,
}: {
  remainingSeconds: number | null;
  evidenceCount: number;
  ideaCount: number;
}) {
  return (
    <dl className="grid grid-cols-3 gap-3 max-[720px]:grid-cols-1">
      <RunMetric
        label="Time remaining"
        value={
          remainingSeconds === null ? 'Estimating…' : `${remainingSeconds}s`
        }
      />
      <RunMetric label="Sources Analyzed" value={String(evidenceCount)} />
      <RunMetric label="Ideas explored" value={String(ideaCount)} />
    </dl>
  );
}

export function ActiveRunView({
  run,
  events,
  evidenceCount,
  ideaCount,
}: ActiveRunViewProps) {
  // Ticks so relative timestamps and the elapsed clock stay honest even while
  // a slow node holds the run without emitting a new event.
  const nowSeconds = useNowTick(30_000);
  const remainingSeconds = estimateRemainingSeconds(run, nowSeconds);
  // Memoized on the events so the 30s clock ticks above don't re-scan the
  // whole event list just to advance timestamps.
  const activity = useMemo(
    () =>
      events
        .filter(event => event.type !== 'status')
        .slice(-10)
        .reverse(),
    [events],
  );
  return (
    <main className="min-h-0 overflow-auto px-8 py-7 max-[720px]:px-4">
      <section className="mx-auto grid w-full max-w-4xl gap-7">
        <div>
          <p className="text-sm font-medium text-cosci-blue">Executing</p>
          <h2 className="mt-1 text-2xl font-medium">Research in progress</h2>
          <RunExecutionProgress run={run} />
        </div>
        <RunMetrics
          remainingSeconds={remainingSeconds}
          evidenceCount={evidenceCount}
          ideaCount={ideaCount}
        />
        <ActivityLog activity={activity} nowSeconds={nowSeconds} />
      </section>
    </main>
  );
}

// The streaming activity timeline, newest first, with an empty-state note
// until the first event lands.
function ActivityLog({
  activity,
  nowSeconds,
}: {
  activity: StreamEvent[];
  nowSeconds: number;
}) {
  return (
    <section aria-label="Activity log">
      <div className="flex items-center gap-2.5">
        <LivePulse />
        <h3 className="text-base font-medium">Live activity</h3>
      </div>
      {activity.length ? (
        <ol className="mt-5">
          {activity.map((event, index) => (
            <ActivityItem
              key={event.seq}
              event={event}
              isLatest={index === 0}
              isLast={index === activity.length - 1}
              now={nowSeconds}
            />
          ))}
        </ol>
      ) : (
        <div className={IDLE_NOTE_CLASSES}>
          <span className={IDLE_DOT_CLASSES} />
          <p className="text-sm text-cosci-muted">
            Warming up — the first steps will appear here in a moment.
          </p>
        </div>
      )}
    </section>
  );
}

function RunMetric({label, value}: {label: string; value: string}) {
  return (
    <div className="rounded-md bg-cosci-hover p-4">
      <dt className="text-xs text-cosci-muted">{label}</dt>
      <dd className="mt-1 text-xl font-medium">{value}</dd>
    </div>
  );
}

// Title, icon, and accent tone for each phase of the live-activity timeline,
// keyed by the base node name (the part before any dotted qualifier, e.g.
// supervisor.plan). One table so a phase's presentation can't half-drift.
interface ActivityMeta {
  title: string;
  icon: IconName;
  tone: string;
}

// The safety screen surfaces under two phase names (the engine node
// `safety_screen` and the dotted `safety.*` event kind); both render the same.
const SAFETY_META: ActivityMeta = {
  title: 'Safety screening',
  icon: 'encrypted',
  tone: 'text-th-warning',
};

const ACTIVITY_META: Record<string, ActivityMeta> = {
  bootstrap: {
    title: 'Initializing run',
    icon: 'settings',
    tone: 'text-cosci-muted',
  },
  created: {title: 'Run created', icon: 'check', tone: 'text-cosci-muted'},
  queued: {title: 'Queued', icon: 'history', tone: 'text-cosci-muted'},
  completed: {title: 'Run complete', icon: 'check', tone: 'text-th-success'},
  supervisor: {
    title: 'Planning strategy',
    icon: 'assignment',
    tone: 'text-th-primary',
  },
  orchestrator: {
    title: 'Coordinating agents',
    icon: 'assignment',
    tone: 'text-th-primary',
  },
  literature_review: {
    title: 'Reviewing literature',
    icon: 'menu_book',
    tone: 'text-cosci-teal',
  },
  generate: {
    title: 'Generating hypotheses',
    icon: 'lightbulb',
    tone: 'text-th-primary',
  },
  reflection: {
    title: 'Reflecting on ideas',
    icon: 'neurology',
    tone: 'text-th-success',
  },
  comprehensive_reflection: {
    title: 'Deep reflection',
    icon: 'neurology',
    tone: 'text-th-success',
  },
  review: {
    title: 'Reviewing hypotheses',
    icon: 'rate_review',
    tone: 'text-th-success',
  },
  deep_verification: {
    title: 'Verifying assumptions',
    icon: 'check',
    tone: 'text-th-success',
  },
  ranking: {
    title: 'Ranking tournament',
    icon: 'emoji_events',
    tone: 'text-th-warning',
  },
  meta_review: {
    title: 'Synthesizing meta-review',
    icon: 'summarize',
    tone: 'text-th-primary',
  },
  research_overview: {
    title: 'Building research overview',
    icon: 'stars',
    tone: 'text-th-primary',
  },
  evolve: {
    title: 'Evolving hypotheses',
    icon: 'edit_square',
    tone: 'text-cosci-blue',
  },
  proximity: {
    title: 'Mapping the idea landscape',
    icon: 'chess',
    tone: 'text-cosci-teal',
  },
  safety_screen: SAFETY_META,
  safety: SAFETY_META,
};

// A payload field as a string, falling back to '' when it is absent.
function payloadFieldOrEmpty(value: unknown): string {
  return String(value ?? '');
}

// The phase a step represents. scientific_task events carry the engine node in
// payload.task and lifecycle events carry it in payload.event; other kinds
// (e.g. safety.intake) are named by their own dotted type.
function activityPhase(event: StreamEvent): string {
  if (event.type === 'scientific_task') {
    return payloadFieldOrEmpty(event.payload.task);
  }
  if (event.type === 'lifecycle') {
    return payloadFieldOrEmpty(event.payload.event);
  }
  return event.type.split('.')[0] ?? event.type;
}

// Meta for a phase, humanizing unknown phases from their node name with the
// default icon/tone.
function activityMeta(phase: string): ActivityMeta {
  const known = ACTIVITY_META[phase];
  if (known) return known;
  const words = phase.replaceAll('_', ' ').replaceAll('.', ' ');
  return {
    title: words.charAt(0).toUpperCase() + words.slice(1),
    icon: 'history',
    tone: 'text-cosci-muted',
  };
}

// A human detail line when the event carries one (a message or a safety
// rationale). Phase-only steps render just their title and timestamp; the task
// field is the phase itself, so it never doubles as the detail.
function activityDetail(event: StreamEvent): string {
  const detail = event.payload.message || event.payload.reason;
  return detail ? String(detail) : '';
}

// Compact relative age of an event, e.g. "just now", "8s ago", "2m ago".
function relativeTime(createdAt: number | undefined, now: number): string {
  if (!createdAt) return '';
  const seconds = Math.max(0, Math.round(now - createdAt));
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}

// Re-renders the caller on an interval so time-based UI (relative timestamps,
// the elapsed clock) advances even when no new events or props arrive.
function useNowTick(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

// A small sonar dot signalling the feed is live.
function LivePulse() {
  return (
    <span className="relative flex size-2.5" aria-hidden="true">
      <span className={PULSE_RING_CLASSES} />
      <span className={PULSE_DOT_CLASSES} />
    </span>
  );
}

// The phase icon disc on the connector rail; the latest step's disc is
// filled and gently pulses so it reads as "happening now".
function ActivityDisc({
  icon,
  tone,
  isLatest,
}: {
  icon: IconName;
  tone: string;
  isLatest: boolean;
}) {
  return (
    <span
      className={joinClasses(
        'relative z-[1] grid size-[2.125rem] shrink-0 place-items-center',
        'rounded-full',
        isLatest ? 'animate-pulse bg-th-primary' : 'bg-cosci-hover',
      )}
    >
      <Icon
        name={icon}
        className={joinClasses(
          'text-[1.15rem]',
          isLatest ? 'text-th-primary-fg' : tone,
        )}
      />
    </span>
  );
}

// One node in the vertical activity timeline: a phase icon on the connector
// rail, then the phase title, its detail, and how long ago it landed.
function ActivityItem({
  event,
  isLatest,
  isLast,
  now,
}: {
  event: StreamEvent;
  isLatest: boolean;
  isLast: boolean;
  now: number;
}) {
  const {title, icon, tone} = activityMeta(activityPhase(event));
  const detail = activityDetail(event);
  return (
    <li className="relative flex gap-4 pb-6 last:pb-0">
      {!isLast && <span aria-hidden="true" className={TIMELINE_RAIL_CLASSES} />}
      <ActivityDisc icon={icon} tone={tone} isLatest={isLatest} />
      <div className="min-w-0 flex-1">
        {/* Sized to the disc and centred on its axis; both paragraphs zero
            their own user-agent margins or the row drifts off-centre. */}
        <div className={TIMELINE_ROW_CLASSES}>
          <p className="my-0 truncate font-medium text-cosci-fg">{title}</p>
          <span className="shrink-0 text-xs text-cosci-muted">
            {relativeTime(event.created_at, now)}
          </span>
        </div>
        {detail ? (
          <p className="mb-0 mt-0.5 line-clamp-2 text-sm text-cosci-muted">
            {detail}
          </p>
        ) : null}
      </div>
    </li>
  );
}
