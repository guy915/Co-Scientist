// The shapes a finished run's Goal Report is delivered in: the report
// payload itself, the research overview it carries, and the derived
// groupings the surface renders from them. Split from `run_types` because
// these describe a run's *output* rather than the run, and because that
// file sits at its line ceiling.

import type {ClaimEvidenceRow, RunMode} from './run_types';

/**
 * Structured contents of a run's final synthesis report. One canonical shape
 * for every provider, built server-side by
 * `report_render.build_report_payload`.
 */
export interface ReportPayload {
  research_goal: string;
  run_mode?: RunMode;
  provider: string;
  /** Ideas released by the safety and contradiction gates. */
  hypothesis_count?: number;
  /** Every idea the run explored, released or not. */
  idea_count?: number;
  /** Released ideas carrying an evidence-supported claim. */
  verified_count?: number;
  evidence_count?: number;
  match_count?: number;
  // counts by classification, e.g. verified/partial/unsupported/unavailable
  citation_summary?: Record<string, number>;
  leaderboard: {id: string; title: string; elo: number}[];
  meta_review?: Record<string, unknown>;
  research_overview?: ResearchOverview;
  knowledge_base?: KnowledgeBaseTopic[];
  agent_insights?: AgentInsights;
  idea_buckets?: {
    high_potential: IdeaBucketEntry[];
    non_viable: IdeaBucketEntry[];
  };
  claim_evidence?: ClaimEvidenceRow[];
  execution_time?: number;
  /**
   * Engine nodes whose output degraded to a placeholder fallback after
   * repeated parse failures (L7). Names the report sections a reader should
   * read as "generation failed" rather than as missing data. Empty/absent on
   * clean runs and on reports written before the field existed.
   */
  degraded_sections?: string[];
  /**
   * What the run could not search, when no literature source was
   * reachable: the reason, the capabilities it lost, and whatever was
   * left to search instead (`none` when nothing was). Absent on a run
   * that retrieved normally and on reports written before the field
   * existed. Distinct from `degraded_sections`, which explains a section
   * the model failed to write -- this explains work never attempted, and
   * nothing else in the report reveals it.
   */
  retrieval_degradation?: {
    reason: string;
    lost: string[];
    floor: string;
  } | null;
}

/** One synthesized technical topic backed by claim-evidence references. */
export interface KnowledgeBaseTopic {
  id: string;
  title: string;
  summary: string;
  detail: string;
  uncertainty?: string;
  reference_ids: string[];
}

/** One meta-review recommendation: where to focus, what to do, and why. */
export interface RecommendedDirection {
  focus_area: string;
  recommendation: string;
  justification: string;
}

/**
 * Run-wide findings and explicit scientific uncertainty.
 *
 * `recommended_directions` admits a bare string because report payloads are
 * persisted: reports written before recommendations kept their three fields
 * hold one flattened string per entry, and those reports still render.
 */
export interface AgentInsights {
  key_findings: string[];
  uncertainties: string[];
  contradictions: string[];
  recommended_directions: (RecommendedDirection | string)[];
  next_experiments: string[];
}

/** An idea's report bucket and the persisted reason for that placement. */
export interface IdeaBucketEntry {
  id: string;
  title: string;
  reason: string;
}

/**
 * A named sub-topic nested one level below a research direction (MO-1):
 * both published exemplars develop "what to research" this way (cf-PICI's
 * "Topic 1..4", ALS's "Areas of Research"). Absent on a direction from a
 * report persisted before this layer existed.
 */
export interface ResearchSubTopic {
  title?: string;
  why?: string;
  what?: string;
  specific_questions?: string[];
}

/** Synthesized roadmap and NIH Specific Aims for a run's top hypotheses. */
export interface ResearchOverview {
  overview?: {
    summary?: string;
    research_directions?: {
      title: string;
      importance: string;
      suggested_experiments: string[];
      // MO-12: the "what is already known" slot ALS's exemplar names
      // "Recent Findings". Absent on a report persisted before it existed.
      recent_findings?: string;
      // MO-1: absent on a report persisted before this layer existed.
      sub_topics?: ResearchSubTopic[];
    }[];
  };
  // The blocks Google's published exemplars print, plus the older
  // introduction/impact pair reports stored before them still carry.
  nih_specific_aims?: {
    disease_description?: string;
    unmet_need?: string;
    proposed_solution?: string;
    aims?: {
      overarching_goal?: string;
      hypothesis?: string;
      reasoning?: string;
      aim?: string;
      rationale?: string;
      approach?: string;
    }[];
    pilot_evaluation?: string;
    introduction?: string;
    impact?: string;
  };
  research_contacts?: {
    candidate_id: string;
    name: string;
    expertise: string;
    justification: string;
    source_id: string;
    source_title: string;
    source_url: string;
    source: string;
    // MO-7: ties the contact back to the direction that surfaced them.
    // Absent on a report persisted before this field existed, and may
    // legitimately be an empty string when the model omits it.
    research_direction?: string;
  }[];
}

/** A persisted run report with its structured payload and markdown path. */
export interface Report {
  id: string;
  run_id: string;
  payload: ReportPayload;
  markdown_path: string;
  /**
   * The rendered Research Overview document (R14-11). Always present on a
   * saved report -- both the current two-document shape and the older,
   * single combined document a run persisted before the split still land
   * here unchanged.
   */
  markdown_text?: string;
  /**
   * The rendered Top Ranking Hypotheses document (R14-11), or null/absent
   * on a report saved before the split. This is the back-compat signal a
   * reader checks: only render a "Top Ranking Hypotheses" tab when this is
   * present, and leave an older run's four tabs exactly as they were.
   */
  markdown_text_ranking?: string | null;
  created_at: number;
}
