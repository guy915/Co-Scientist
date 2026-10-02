import type {IconName} from '@/components/icon';
import type {RunEventActivity} from '@/api/wire_common';
import type {StreamEvent} from '@/hooks/use_run_stream';
import {capitalizeTerm} from '@/lib/text';

export interface ActivityMeta {
  title: string;
  icon: IconName;
  tone: string;
}

const SAFETY_META: ActivityMeta = {
  title: 'Safety screening',
  icon: 'encrypted',
  tone: 'text-th-warning',
};

// Server activity labels also supply the matching legacy-node presentation.
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

// Older stored events and lifecycle events use node names instead.
const ACTIVITY_META: Record<string, ActivityMeta> = {
  bootstrap: {
    title: 'Initializing run',
    icon: 'settings',
    tone: 'text-cosci-muted',
  },
  created: {title: 'Run created', icon: 'check', tone: 'text-cosci-muted'},
  queued: {title: 'Queued', icon: 'history', tone: 'text-cosci-muted'},
  completed: {title: 'Run complete', icon: 'check', tone: 'text-th-success'},
  supervisor: ACTIVITY_KEY_META.planning,
  orchestrator: {
    title: 'Coordinating agents',
    icon: 'assignment',
    tone: 'text-th-primary',
  },
  literature_review: ACTIVITY_KEY_META.literature_search,
  generate: ACTIVITY_KEY_META.drafting,
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
  review: ACTIVITY_KEY_META.review,
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
  meta_review: ACTIVITY_KEY_META.synthesis,
  research_overview: {
    title: 'Building research overview',
    icon: 'stars',
    tone: 'text-th-primary',
  },
  evolve: ACTIVITY_KEY_META.evolution,
  proximity: ACTIVITY_KEY_META.deduplication,
  safety_screen: SAFETY_META,
  safety: SAFETY_META,
};

function activityPhase(event: StreamEvent): string {
  if (event.type === 'scientific_task') {
    return String(event.payload.task ?? '');
  }
  if (event.type === 'lifecycle') {
    return String(event.payload.event ?? '');
  }
  return event.type.split('.')[0] ?? event.type;
}

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

interface ResolvedActivity {
  key: string;
  meta: ActivityMeta;
}

function resolveActivity(event: StreamEvent): ResolvedActivity {
  const activity = event.payload.activity;
  if (isClassifiedActivity(activity)) {
    return {key: activity, meta: ACTIVITY_KEY_META[activity]};
  }
  const phase = activityPhase(event);
  return {key: phase, meta: legacyActivityMeta(phase)};
}

export function activityDetail(event: StreamEvent): string {
  const detail = event.payload.message || event.payload.reason;
  return detail ? String(detail) : '';
}

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

export interface ActivityGroup {
  key: string;
  meta: ActivityMeta;
  events: StreamEvent[];
}

// Group adjacent events only, so a later return to a phase stays visible.
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

export function windowedActivityGroups(
  events: StreamEvent[],
  limit: number,
): ActivityGroup[] {
  return groupConsecutiveActivity(events).slice(-limit).reverse();
}
