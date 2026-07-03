/**
 * Single source of truth for pipeline event type → human label.
 *
 * The mock workflow and (post-unification) the real-engine adapter both emit
 * the same canonical, unprefixed event vocabulary. This module is the one home
 * for turning those types into display labels, so overview, log console, and
 * chat workspace render identically instead of each carrying its own map.
 */

/** Canonical event type → display label. Wording follows the overview tab. */
export const EVENT_LABELS: Record<string, string> = {
  'supervisor.plan': 'Supervisor',
  'intake.scope': 'Intake',
  'safety.intake': 'Safety (intake)',
  literature_review: 'Literature retrieval',
  generate: 'Generation',
  reflection: 'Reflection',
  review: 'Review',
  proximity: 'Proximity',
  ranking: 'Ranking',
  evolve: 'Evolution',
  meta_review: 'Meta-review',
  deep_verification: 'Deep verification',
  citation_audit: 'Citation audit',
  research_overview: 'Research overview',
  'safety.final': 'Safety (final)',
  report: 'Report synthesis',
  status: 'Status',
  lifecycle: 'Lifecycle',
};

const LEGACY_ENGINE_PREFIX = 'engine.';

/** Prettify a raw type by turning `.`/`_` separators into spaces. */
function prettify(type: string): string {
  return type.replace(/[._]/g, ' ');
}

/**
 * Resolve a pipeline event type to a display label.
 *
 * Resolution order:
 * 1. Canonical lookup in {@link EVENT_LABELS}.
 * 2. LEGACY fallback — old persisted runs (already in existing databases)
 *    emitted `engine.<node>` types before the adapter was unified. Strip the
 *    `engine.` prefix and retry the lookup so replayed historical runs still
 *    render friendly labels.
 * 3. Prettify the raw type (replace `.`/`_` with spaces).
 *
 * @param type The event type as emitted/persisted.
 * @returns A human-readable label.
 */
export function formatEventLabel(type: string): string {
  const direct = EVENT_LABELS[type];
  if (direct) return direct;

  if (type.startsWith(LEGACY_ENGINE_PREFIX)) {
    const stripped = type.slice(LEGACY_ENGINE_PREFIX.length);
    return EVENT_LABELS[stripped] ?? prettify(stripped);
  }

  return prettify(type);
}
