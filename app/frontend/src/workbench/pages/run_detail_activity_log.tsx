import {useState} from 'react';
import {Icon, type IconName} from '@/components/icon';
import type {StreamConnectionState, StreamEvent} from '@/hooks/use_run_stream';
import {joinClasses} from '../classes';
import {
  type ActivityGroup,
  type ActivityMeta,
  activityDetail,
  relativeTime,
} from './run_detail_activity';

/**
 * The live run view's streaming activity timeline: the "Live activity"
 * header (connection pulse/status note) and the list of activity cards
 * below it. Split out of run_detail_active.tsx to keep that file under the
 * repo's 500-line cap -- this half draws the cards; run_detail_activity.ts
 * (split out alongside it, same reason) resolves and groups the events.
 */

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

// A small sonar dot signalling the feed is live.
function LivePulse() {
  return (
    <span className="relative flex size-2.5" aria-hidden="true">
      <span className={PULSE_RING_CLASSES} />
      <span className={PULSE_DOT_CLASSES} />
    </span>
  );
}

// Labels for every transport state that is not a healthy open connection.
// 'open' and a missing state (a stream double with no transport field)
// render nothing — neither is a degraded condition to surface.
const STREAM_STATUS_LABEL: Record<
  Exclude<StreamConnectionState, 'open'>,
  string
> = {
  connecting: 'Connecting...',
  reconnecting: 'Reconnecting...',
  disconnected: 'Stream disconnected',
};

// The pulse dot claims the feed is live, so a stream that is not open gets
// this static marker in its place instead of passing as healthy.
function StreamStatusDot({
  connection,
}: {
  connection: Exclude<StreamConnectionState, 'open'>;
}) {
  return (
    <span className="relative flex size-2.5" aria-hidden="true">
      <span
        className={joinClasses(
          'inline-flex size-2.5 rounded-full',
          connection === 'connecting' ? 'bg-cosci-muted' : 'bg-th-warning',
        )}
      />
    </span>
  );
}

// A quiet status line naming the stream's degraded transport state. It sits
// in the activity header because that heading is the element claiming the
// feed is live; role="status" lets assistive tech hear the change.
function StreamStatusNote({
  connection,
}: {
  connection: StreamConnectionState | undefined;
}) {
  if (connection === undefined || connection === 'open') return null;
  return (
    <span
      role="status"
      className={joinClasses(
        'text-xs',
        connection === 'connecting' ? 'text-cosci-muted' : 'text-th-warning',
      )}
    >
      {STREAM_STATUS_LABEL[connection]}
    </span>
  );
}

// The phase icon disc on the connector rail; the latest card's disc is
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

// One event, rendered as its own timeline row: a phase icon on the
// connector rail, then the phase title, its detail, and how long ago it
// landed. Used both for single-event groups and for each row of an
// expanded multi-event group's detail list.
function ActivityItem({
  event,
  meta,
  isLatest,
  isLast,
  now,
}: {
  event: StreamEvent;
  meta: ActivityMeta;
  isLatest: boolean;
  isLast: boolean;
  now: number;
}) {
  const detail = activityDetail(event);
  return (
    <li className="relative flex gap-4 pb-6 last:pb-0">
      {!isLast && <span aria-hidden="true" className={TIMELINE_RAIL_CLASSES} />}
      <ActivityDisc icon={meta.icon} tone={meta.tone} isLatest={isLatest} />
      <div className="min-w-0 flex-1">
        {/* Sized to the disc and centred on its axis; both paragraphs zero
            their own user-agent margins or the row drifts off-centre. */}
        <div className={TIMELINE_ROW_CLASSES}>
          <p className="my-0 truncate font-medium text-cosci-fg">
            {meta.title}
          </p>
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

// The collapsed title row of a multi-event card: the activity title with a
// step count, plus the expand/collapse toggle. A separate function from its
// caller so the branch that renders the (visible only when expanded) detail
// list doesn't also have to fit under the same line/complexity ceiling.
function GroupSummaryRow({
  group,
  isLatest,
  now,
  expanded,
  onToggle,
}: {
  group: ActivityGroup;
  isLatest: boolean;
  now: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  const count = group.events.length;
  const latest = group.events[group.events.length - 1];
  // The newest group is still accumulating steps, so its time slot reads as
  // an ongoing state rather than a relative age that would read "just now"
  // and then go stale a second later.
  const timeLabel = isLatest
    ? 'In progress'
    : relativeTime(latest.created_at, now);
  return (
    <>
      <div className={TIMELINE_ROW_CLASSES}>
        <p className="my-0 truncate font-medium text-cosci-fg">
          {group.meta.title} · {count} steps
        </p>
        <span className="shrink-0 text-xs text-cosci-muted">{timeLabel}</span>
      </div>
      {/* The visible label stays put across a toggle -- aria-expanded is
          what communicates open/closed, so the accessible name doesn't
          swap out from under anyone relying on it. */}
      <button
        type="button"
        aria-expanded={expanded}
        aria-label={`${count} steps for ${group.meta.title}`}
        onClick={onToggle}
        className={joinClasses(
          'mt-1 flex items-center gap-1 rounded text-xs font-medium',
          'text-cosci-muted hover:text-cosci-fg',
          'focus-visible:outline focus-visible:outline-2',
          'focus-visible:outline-offset-2 focus-visible:outline-th-primary',
        )}
      >
        <span aria-hidden="true">{expanded ? 'Hide' : 'Show'} steps</span>
        <Icon name={expanded ? 'expand_less' : 'expand_more'} />
      </button>
    </>
  );
}

// The expanded panel of a multi-event card: each grouped event as its own
// compact row, oldest first (matching the group's own arrival order).
function GroupEventList({group, now}: {group: ActivityGroup; now: number}) {
  return (
    <ol className="mt-2 flex flex-col gap-1.5 border-s border-cosci-border ps-4">
      {group.events.map(event => (
        <li
          key={event.seq}
          className="flex items-baseline justify-between gap-3"
        >
          <span className="truncate text-xs text-cosci-muted">
            {activityDetail(event) || group.meta.title}
          </span>
          <span className="shrink-0 text-xs text-cosci-muted">
            {relativeTime(event.created_at, now)}
          </span>
        </li>
      ))}
    </ol>
  );
}

// One card in the vertical activity timeline. A single-event group renders
// as a plain ActivityItem; a multi-event group renders as a collapsible
// card carrying a step count. Collapsed by default -- the expand state is
// local to the card, keyed in the caller by the group's first event's
// `seq`, which never changes as the group grows (new same-activity events
// only append to it), so expanding a still-live card does not reset when
// the next step arrives.
function ActivityGroupCard({
  group,
  isLatest,
  isLast,
  now,
}: {
  group: ActivityGroup;
  isLatest: boolean;
  isLast: boolean;
  now: number;
}) {
  const [expanded, setExpanded] = useState(false);
  if (group.events.length === 1) {
    return (
      <ActivityItem
        event={group.events[0]}
        meta={group.meta}
        isLatest={isLatest}
        isLast={isLast}
        now={now}
      />
    );
  }
  return (
    <li className="relative flex gap-4 pb-6 last:pb-0">
      {!isLast && <span aria-hidden="true" className={TIMELINE_RAIL_CLASSES} />}
      <ActivityDisc
        icon={group.meta.icon}
        tone={group.meta.tone}
        isLatest={isLatest}
      />
      <div className="min-w-0 flex-1">
        <GroupSummaryRow
          group={group}
          isLatest={isLatest}
          now={now}
          expanded={expanded}
          onToggle={() => setExpanded(value => !value)}
        />
        {expanded ? <GroupEventList group={group} now={now} /> : null}
      </div>
    </li>
  );
}

// The streaming activity timeline, newest first, with an empty-state note
// until the first card lands.
export function ActivityLog({
  groups,
  connection,
  nowSeconds,
}: {
  groups: ActivityGroup[];
  connection: StreamConnectionState | undefined;
  nowSeconds: number;
}) {
  return (
    <section aria-label="Activity log">
      <div className="flex items-center gap-2.5">
        {connection === 'open' || connection === undefined ? (
          <LivePulse />
        ) : (
          <StreamStatusDot connection={connection} />
        )}
        {/* `my-0`: an <h3>'s 1em user-agent block margin does not collapse
            inside this flex row, so it survived as 16px of padding above
            the heading. The section's own gap already spaces the cards
            from this log, and that extra 16px landed on one side of them
            only — 44px of white below the cards against 27px above. */}
        <h3 className="my-0 text-base font-medium">Live activity</h3>
        <StreamStatusNote connection={connection} />
      </div>
      {groups.length ? (
        <ol className="mt-5">
          {groups.map((group, index) => (
            <ActivityGroupCard
              key={group.events[0].seq}
              group={group}
              isLatest={index === 0}
              isLast={index === groups.length - 1}
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
