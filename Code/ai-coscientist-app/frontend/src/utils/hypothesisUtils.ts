import type { Hypothesis } from "@/types/hypothesis";

const KNOWN_KEYS = new Set([
  "text", "hypothesis", "explanation", "literature_grounding", "experiment",
  "id", "hypothesis_id", "score", "elo_rating", "rank", "reviews",
  "evolution_history", "similarity_cluster_id", "cluster_id", "reflection_notes",
  "win_count", "loss_count", "total_matches", "win_rate", "justification",
  "literature_review_used", "novelty_validation", "generation_method",
  "debate_id", "papers_used", "enrichments",
]);

/**
 * Collect any keys not in the known set so domain-specific fields
 * (e.g. related_cves) pass through to the hypothesis object.
 * Also unpacks enrichments dict subkeys as top-level fields so that
 * DomainCustomFields can access e.g. hypothesis["related_cves"] directly.
 */
function collectDynamicFields(hyp: Record<string, unknown>): Record<string, unknown> {
  const extras: Record<string, unknown> = {};
  for (const key of Object.keys(hyp)) {
    if (!KNOWN_KEYS.has(key)) {
      extras[key] = hyp[key];
    }
  }

  // unpack enrichments subkeys as top-level fields
  const enrichments = hyp.enrichments;
  if (enrichments && typeof enrichments === "object" && !Array.isArray(enrichments)) {
    for (const [key, value] of Object.entries(enrichments as Record<string, unknown>)) {
      extras[key] = value;
    }
  }

  return extras;
}

/**
 * Normalize hypothesis data to ensure all required fields have values
 */
export function normalizeHypothesis(hyp: any): Hypothesis {
  return {
    text: hyp.text || hyp.hypothesis || "",
    explanation: hyp.explanation,
    literature_grounding: hyp.literature_grounding,
    experiment: hyp.experiment,
    id: hyp.id || hyp.hypothesis_id || "",
    score: typeof hyp.score === "number" ? hyp.score : 0,
    elo_rating: typeof hyp.elo_rating === "number" ? hyp.elo_rating : 1200,
    rank: hyp.rank,
    reviews: Array.isArray(hyp.reviews) ? hyp.reviews : [],
    evolution_history: Array.isArray(hyp.evolution_history) ? hyp.evolution_history : [],
    similarity_cluster_id: hyp.similarity_cluster_id || hyp.cluster_id,
    reflection_notes: hyp.reflection_notes,
    win_count: typeof hyp.win_count === "number" ? hyp.win_count : 0,
    loss_count: typeof hyp.loss_count === "number" ? hyp.loss_count : 0,
    total_matches: typeof hyp.total_matches === "number" ? hyp.total_matches : 0,
    win_rate: typeof hyp.win_rate === "number" ? hyp.win_rate : 0,
    literature_review_used: hyp.literature_review_used,
    novelty_validation: hyp.novelty_validation,
    generation_method: hyp.generation_method,
    debate_id: hyp.debate_id,
    papers_used: Array.isArray(hyp.papers_used) ? hyp.papers_used : undefined,
    ...collectDynamicFields(hyp),
  };
}

/**
 * Normalize an array of hypotheses
 */
export function normalizeHypotheses(hypotheses: any[]): Hypothesis[] {
  if (!Array.isArray(hypotheses)) {
    return [];
  }
  return hypotheses.map(normalizeHypothesis);
}
