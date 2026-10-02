import type {StreamEvent} from '@/hooks/use_run_stream';

export type RunDataKey =
  | 'hypotheses'
  | 'evidence'
  | 'matches'
  | 'reviews'
  | 'claimEvidence'
  | 'outcomes'
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
  'scientist.outcome': ['outcomes'],
  proximity: ['hypotheses'],
  ranking: ['hypotheses', 'matches'],
  evolve: ['hypotheses', 'claimEvidence'],
  report: ['report'],
};

// Collects the RunDataKey set a batch of newly-arrived events touches
// (multiple event types can map to the same key; see EVENT_DATA_KEYS).
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

export function shouldRefreshOutcomes(keys?: ReadonlySet<RunDataKey>): boolean {
  return keys === undefined || keys.has('outcomes');
}
