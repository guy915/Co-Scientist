// Types for computational-discovery runs: the program a run is evolving,
// each attempt at it, how those attempts are scored, and the report the
// run leaves behind. Kept out of `run_types` so that file stays under the
// line ceiling, and because nothing here is meaningful for a hypothesis
// run.

import type {Report} from './report_types';

/** One attempt at the program a discovery run is evolving. */
export interface CodeVariant {
  id: string;
  run_id: string;
  // id of the variant this one was derived from; null for the seed
  parent_id: string | null;
  // 0 for the seed, incremented once per generation
  generation: number;
  // dense attempt number within the run, starting at 1. Failed attempts
  // keep their number: the sequence is only honest if what went nowhere
  // still occupies a place in it.
  ordinal: number;
  // named code operator that produced this child; null for the seed
  operator: string | null;
  rationale: string;
  // the patch applied to the parent, as the model wrote it
  diff: string;
  // the whole program at this variant, {path: contents}
  source: Record<string, string>;
  created_by_agent: string;
  created_at: number;
  // 'pending' before evaluation, then a code_eval status
  status: string;
  // already sign-corrected, so higher is always better. null means the
  // variant has no position in the ordering at all -- which is not the
  // same as a score of zero, and must not be rendered as one.
  fitness: number | null;
  is_best_so_far: boolean;
  duration_seconds: number | null;
  stages: VariantStage[];
  // Every objective's sign-corrected score, in the run's declared order;
  // `fitness` is the first entry. Higher is better on every axis, so a
  // minimized metric arrives negated.
  objective_values: (number | null)[];
  // Raw behaviour measurements: what move produced this variant, how
  // deeply nested it is, what it depends on. Not the archive cell --
  // under an adaptive grid a variant's cell depends on every other
  // variant, so it is derived when read, never stored.
  behaviour: Record<string, string | number>;
  // Whether no other variant beats it on every objective at once. A
  // property of the whole set, so it is computed per response rather
  // than stored -- one new variant can take an older one off the front.
  is_pareto_optimal?: boolean;
  // present on the detail response only
  metrics?: Record<string, number>;
  artifacts?: Record<string, string>;
}

/** One cascade stage's outcome within a variant's evaluation. */
export interface VariantStage {
  name: string;
  status: string;
  exit_code: number | null;
  duration_seconds: number;
}

/** One objective a discovery run is optimizing. */
export interface DiscoveryObjective {
  metric: string;
  direction: string;
}

/** A run's variants plus what the surface needs to read them. */
export interface CodeVariantPage {
  variants: CodeVariant[];
  // Declared order; the first is the primary, which `fitness` reports.
  objectives: DiscoveryObjective[];
  // Distinct archive cells reached. The number the diversity mechanism
  // exists to move, so it is reported rather than inferred.
  niches_occupied: number;
  // How evenly those cells are filled, 0 to 1. Reported beside the
  // count because the count alone can be high while the run is still
  // collapsed: forty variants in one cell and one in each of five
  // others reaches six cells and has explored almost nothing.
  niche_evenness: number;
}

/**
 * A discovery spec as sent when creating a run.
 *
 * The same shape as `DiscoveryConfig` below, with the fields the backend
 * requires made non-optional here: a spec missing any of them is refused
 * at creation, so a caller that can send one has already decided them.
 */
export interface DiscoverySpec {
  objective: DiscoveryObjective;
  stages: {name: string; argv: string[]; timeout_seconds?: number}[];
  seed_source: Record<string, string>;
  max_generations?: number;
  children_per_generation?: number;
}

/** What a discovery run optimizes, and how it measures it. */
export interface DiscoveryConfig {
  objective?: {metric?: string; direction?: string};
  objectives?: {metric?: string; direction?: string}[];
  descriptors?: {feature?: string; bins?: number[]}[];
  grid?: {strategy?: string; cells?: number};
  stages?: {name?: string; argv?: string[]}[];
  metrics_path?: string;
  seed_source?: Record<string, string>;
  max_generations?: number;
  children_per_generation?: number;
}

/**
 * A discovery run's report payload.
 *
 * Deliberately shares no field name with `ReportPayload`'s counts: a
 * discovery run produces no hypotheses, no evidence and no matches, so
 * borrowing those names would leave every surface reading a number
 * named for something the run never had.
 */
export interface DiscoveryReportPayload {
  report_kind: 'discovery';
  research_goal: string;
  run_mode?: string;
  provider: string;
  // Declared order; the first is the primary, which `best_fitness`
  // reports. Carried so a reader can undo the sign correction: without
  // the direction, a minimized metric renders as negative seconds.
  objectives: DiscoveryObjective[];
  // every attempt, failures included
  variant_count: number;
  // attempts that produced a usable score
  scored_count: number;
  generation_count: number;
  // Distinct archive cells reached, and how evenly they were filled.
  // Both, because either alone misleads -- see CodeVariantPage.
  niches_occupied: number;
  niche_evenness: number;
  best_variant_id: string | null;
  best_fitness: number | null;
}

/**
 * Narrows a run's report to the discovery shape, or null when it is a
 * hypothesis report (or there is none yet).
 *
 * @param report The run's persisted report, if any.
 * @returns The discovery payload, or null.
 */
export function discoveryReportPayload(
  report: Report | null,
): DiscoveryReportPayload | null {
  if (report?.payload.report_kind !== 'discovery') return null;
  return report.payload as unknown as DiscoveryReportPayload;
}

// The objective a run declared first, in whichever of the two shapes
// it used: `objectives` for several, `objective` for one.
function declaredObjective(config: DiscoveryConfig | undefined) {
  if (!config) return undefined;
  const declared = config.objectives ?? [];
  return declared.length > 0 ? declared[0] : config.objective;
}

/**
 * A discovery run's primary objective, as declared in its config.
 *
 * Needed wherever a stored score is printed: sign correction can only
 * be undone with the direction in hand.
 *
 * @param config A run's discovery block, if it has one.
 * @returns The primary objective, or undefined.
 */
export function primaryObjective(
  config: DiscoveryConfig | undefined,
): DiscoveryObjective | undefined {
  const raw = declaredObjective(config);
  if (!raw?.metric) return undefined;
  return {metric: raw.metric, direction: raw.direction ?? 'maximize'};
}
