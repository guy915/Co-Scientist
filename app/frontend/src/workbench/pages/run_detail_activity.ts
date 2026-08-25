import type {IconName} from '@/components/icon';
import type {RunEventActivity} from '@/api/run_types';
import type {StreamEvent} from '@/hooks/use_run_stream';
import {capitalizeTerm} from '@/lib/text';

/**
 * How the live activity log turns a raw event stream into cards: resolving
 * each event's presentation (title/icon/tone) and grouping consecutive
 * events that share an activity. Pure logic, no rendering -- split out of
 * run_detail_activity_log.tsx (itself split out of run_detail_active.tsx for
 * the repo's 500-line cap) once the pair together still didn't fit; that
 * file owns everything about drawing the cards this module describes.
 */

// Title, icon, and accent tone for a card. One shape shared by the
// closed-vocabulary table and the legacy fallback table below so a card's
// presentation can't half-drift between the two paths.
export interface ActivityMeta {
  title: string;
  icon: IconName;
  tone: string;
}

// The safety screen surfaces under several names across both tables (the
// activity value, the engine node `safety_screen`, and the dotted
// `safety.*` event kind); all render the same.
const SAFETY_META: ActivityMeta = {
  title: 'Safety screening',
  icon: 'encrypted',
  tone: 'text-th-warning',
};

// Presentation keyed on the server-computed `payload.activity` discriminator
// (see RunEventActivity's docstring) -- the primary source for a card's
// label, icon, and tone. Typed to exclude 'other' so this table can never
// answer the catch-all value: 'other' is what the server emits both for a
// genuinely unclassifiable event *and* for every control-plane lifecycle
// event (created/queued/bootstrap/completed aren't engine nodes), and the
// second case has a perfectly good name available from the legacy
// inference below -- so 'other' falls through to that table too, on the
// same branch as a missing `activity` key. resolveActivity is what enforces
// this split.
const ACTIVITY_KEY_META: Record<
  Exclude<RunEventActivity, 'other'>,
  ActivityMeta
> = {
  planning: {
    title: 'Planning strategy',
    icon: 'assignment',
    tone: 'text-th-primary',
  },
  literature_search: {
    title: 'Reviewing literature',
    icon: 'menu_book',
    tone: 'text-cosci-teal',
  },
  drafting: {
    title: 'Generating hypotheses',
    icon: 'lightbulb',
    tone: 'text-th-primary',
  },
  review: {
    title: 'Reviewing hypotheses',
    icon: 'rate_review',
    tone: 'text-th-success',
  },
  tournament: {
    title: 'Comparing ideas',
    icon: 'emoji_events',
    tone: 'text-th-warning',
  },
  evolution: {
    title: 'Evolving hypotheses',
    icon: 'edit_square',
    tone: 'text-cosci-blue',
  },
  deduplication: {
    title: 'Mapping the idea landscape',
    icon: 'chess',
    tone: 'text-cosci-teal',
  },
  synthesis: {
    title: 'Synthesizing meta-review',
    icon: 'summarize',
    tone: 'text-th-primary',
  },
  safety: SAFETY_META,
};

// Legacy presentation keyed by the base node name, parsed out of the
// event's own `type`/payload. This was once the only source for a card's
// presentation; it is now the fallback used solely when an event carries no
// `activity` (persisted before the field existed, or replayed across a
// resumed run) or carries the unclassified 'other' -- see ACTIVITY_KEY_META
// above for why 'other' lands here too. Kept instead of deleted because
// several of these names (bootstrap/created/queued/completed) are
// control-plane lifecycle events the closed vocabulary never classifies.
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

// The legacy phase a step represents. scientific_task events carry the
// engine node in payload.task and lifecycle events carry it in
// payload.event; other kinds (e.g. safety.intake) are named by their own
// dotted type. Used only by the fallback path -- see resolveActivity.
function activityPhase(event: StreamEvent): string {
  if (event.type === 'scientific_task') {
    return payloadFieldOrEmpty(event.payload.task);
  }
  if (event.type === 'lifecycle') {
    return payloadFieldOrEmpty(event.payload.event);
  }
  return event.type.split('.')[0] ?? event.type;
}

// Fallback meta for a phase, humanizing unknown phases from their node name
// with the default icon/tone.
function legacyActivityMeta(phase: string): ActivityMeta {
  const known = ACTIVITY_META[phase];
  if (known) return known;
  const words = phase.replaceAll('_', ' ').replaceAll('.', ' ');
  return {
    title: capitalizeTerm(words),
    icon: 'history',
    tone: 'text-cosci-muted',
  };
}

function isClassifiedActivity(
  value: unknown,
): value is Exclude<RunEventActivity, 'other'> {
  return typeof value === 'string' && value in ACTIVITY_KEY_META;
}

// One event's card presentation plus the key consecutive events group on.
interface ResolvedActivity {
  key: string;
  meta: ActivityMeta;
}

// Resolve one event to its card presentation: the server's `payload.activity`
// when it names a specific activity, the legacy node-name inference
// otherwise (see the two tables above for the exact fallback rule).
function resolveActivity(event: StreamEvent): ResolvedActivity {
  const activity = event.payload.activity;
  if (isClassifiedActivity(activity)) {
    return {key: activity, meta: ACTIVITY_KEY_META[activity]};
  }
  const phase = activityPhase(event);
  return {key: phase, meta: legacyActivityMeta(phase)};
}

// A human detail line when the event carries one (a message or a safety
// rationale). Phase-only steps render just their title and timestamp; the
// task field is the phase itself, so it never doubles as the detail.
export function activityDetail(event: StreamEvent): string {
  const detail = event.payload.message || event.payload.reason;
  return detail ? String(detail) : '';
}

// Compact relative age of an event, e.g. "just now", "8s ago", "2m ago".
export function relativeTime(
  createdAt: number | undefined,
  now: number,
): string {
  if (!createdAt) return '';
  const seconds = Math.max(0, Math.round(now - createdAt));
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}

/** One card in the activity timeline: either a single event, or a run of
 * consecutive events sharing an activity. */
export interface ActivityGroup {
  key: string;
  meta: ActivityMeta;
  events: StreamEvent[];
}

// Groups ADJACENT events sharing an activity into one card, so a run of
// identical steps (a tournament's many matches) collapses to one row
// instead of one apiece. Only consecutive runs merge -- a later return to
// the same activity starts a new group, because the events' order is
// exactly the information this log exists to show.
function groupConsecutiveActivity(events: StreamEvent[]): ActivityGroup[] {
  const groups: ActivityGroup[] = [];
  for (const event of events) {
    const resolved = resolveActivity(event);
    const current = groups.at(-1);
    if (current && current.key === resolved.key) {
      current.events.push(event);
    } else {
      groups.push({key: resolved.key, meta: resolved.meta, events: [event]});
    }
  }
  return groups;
}

// The last `limit` groups, newest first. The window bounds distinct
// activities shown, not raw events: without this, a long tournament is
// `limit` rows of one match apiece and every other phase of the run has
// already scrolled out of the log by the time it would matter.
export function windowedActivityGroups(
  events: StreamEvent[],
  limit: number,
): ActivityGroup[] {
  return groupConsecutiveActivity(events).slice(-limit).reverse();
}
