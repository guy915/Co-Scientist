export interface PaperReference {
  title: string;
  url?: string;
  authors?: string[];
  year?: number;
  venue?: string;
  source?: string;
  pdf_links?: string[];
}

// Citation key sources stored in citation_map (e.g. {"P1": ..., "KG1": ...})

export interface PaperCitation {
  type: "paper";
  title: string;
  url?: string;
  authors?: string[];
  year?: number;
  pdf_links?: string[];
}

export interface KGCitation {
  type: "knowledge_graph";
  display: string;  // e.g. "INDRA: KRAS → RAF1 [Activation] (belief: 0.95)"
  tool_id?: string;
  data?: Record<string, unknown>;
}

export type CitationSource = PaperCitation | KGCitation;

export interface Hypothesis {
  hypothesis?: string; // Hypothesis text
  text?: string; // alias for hypothesis
  explanation?: string; // Step-by-step layman explanation
  literature_grounding?: string; // Grounding text with inline [P1]/[KG1] citation keys
  experiment?: string; // Practical experiment design to test the hypothesis
  id?: string;
  score: number;
  elo_rating: number;
  rank?: number;
  reviews: Review[];
  evolution_history: string[];
  similarity_cluster_id?: string;
  reflection_notes?: string;
  win_count: number;
  loss_count: number;
  total_matches: number;
  win_rate: number;
  justification?: string;
  literature_review_used?: string;
  novelty_validation?: string; // Summary of novelty validation (tool-based generation)
  generation_method?: string;
  debate_id?: number;
  citation_map?: Record<string, CitationSource>; // resolves [P1], [KG1] keys to source metadata
}

export interface Review {
  scores: { [key: string]: number };
  review_summary?: string;
  overall_score?: number;
  feedback?: string;
  constructive_feedback?: string;
  strengths?: string;
  weaknesses?: string;
  detailed_feedback?: object;
  safety_ethical_concerns?: string;
}
