// Types for computational-discovery runs: the program a run is evolving,
// each attempt at it, and how those attempts are scored. Kept out of
// `run_types` so that file stays under the line ceiling, and because
// nothing here is meaningful for a hypothesis run.

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

/** What a discovery run optimizes, and how it measures it. */
export interface DiscoveryConfig {
  objective?: {metric?: string; direction?: string};
  stages?: {name?: string; argv?: string[]}[];
  metrics_path?: string;
  seed_source?: Record<string, string>;
  max_generations?: number;
  children_per_generation?: number;
  parents_per_generation?: number;
}
