import type { AgentOutput } from "@/types/agents";
import type { Hypothesis } from "@/types/hypothesis";

export const mockAgentOutputs: AgentOutput[] = [
  {
    name: "Supervisor",
    content: JSON.stringify({
      research_goal_analysis: {
        goal_summary: "Investigate novel mechanisms for targeted drug delivery in cancer treatment",
        key_areas: [
          "Nanoparticle-based delivery systems",
          "Tumor microenvironment targeting",
          "Drug release mechanisms",
        ],
      },
      workflow_plan: {
        generation_phase: {
          quantity_target: 5,
          diversity_targets: "High diversity across delivery mechanisms",
          strategies: ["Bio-inspired", "Material science", "Clinical viability"],
        },
        review_phase: {
          reviews_per_hypothesis: 3,
        },
      },
    }),
    parsed: {
      research_goal_analysis: {
        goal_summary: "Investigate novel mechanisms for targeted drug delivery in cancer treatment",
        key_areas: [
          "Nanoparticle-based delivery systems",
          "Tumor microenvironment targeting",
          "Drug release mechanisms",
        ],
      },
      workflow_plan: {
        generation_phase: {
          quantity_target: 5,
          diversity_targets: "High diversity across delivery mechanisms",
          strategies: ["Bio-inspired", "Material science", "Clinical viability"],
        },
        review_phase: {
          reviews_per_hypothesis: 3,
        },
      },
    },
    timestamp: Date.now() - 50000,
    phase: "initial_generation",
  },
  {
    name: "HypothesisGenerator",
    content: JSON.stringify({
      hypotheses: [
        {
          text: "pH-responsive nanoparticles can enhance drug delivery to acidic tumor microenvironments",
        },
        { text: "Magnetic nanoparticles guided by external fields enable precise tumor targeting" },
        { text: "Cell-penetrating peptides improve intracellular drug delivery efficiency" },
      ],
    }),
    parsed: {
      hypotheses: [
        {
          text: "pH-responsive nanoparticles can enhance drug delivery to acidic tumor microenvironments",
        },
        { text: "Magnetic nanoparticles guided by external fields enable precise tumor targeting" },
        { text: "Cell-penetrating peptides improve intracellular drug delivery efficiency" },
      ],
    },
    timestamp: Date.now() - 40000,
    phase: "initial_generation",
  },
];

export const mockHypotheses: Hypothesis[] = [
  {
    text: "pH-responsive nanoparticles utilizing tumor microenvironment acidity (pH 6.5-6.8) can achieve selective drug release with minimal systemic toxicity",
    id: "hyp_001",
    score: 8.7,
    elo_rating: 1523,
    rank: 1,
    reviews: [
      {
        scores: {
          novelty: 4,
          scientific_validity: 5,
          feasibility: 4,
          specificity: 5,
          impact_potential: 4,
          clarity: 5,
        },
        review_summary: "Highly promising approach with strong scientific foundation",
        overall_score: 0.87,
        constructive_feedback: "Consider addressing potential pH heterogeneity within tumors",
        strengths: "Well-defined mechanism, clinically relevant",
        weaknesses: "May require optimization for different tumor types",
      },
    ],
    evolution_history: [
      "Initial hypothesis generated",
      "Refined to include specific pH range",
      "Added toxicity consideration",
    ],
    win_count: 12,
    loss_count: 3,
    total_matches: 15,
    win_rate: 0.8,
  },
  {
    text: "Magnetic nanoparticles with externally controlled guidance systems enable real-time adjustment of drug delivery targeting",
    id: "hyp_002",
    score: 8.2,
    elo_rating: 1487,
    rank: 2,
    reviews: [
      {
        scores: {
          novelty: 5,
          scientific_validity: 4,
          feasibility: 3,
          specificity: 4,
          impact_potential: 5,
          clarity: 4,
        },
        review_summary: "Innovative but faces technical challenges",
        overall_score: 0.82,
        constructive_feedback: "Need to address magnetic field penetration depth limitations",
        strengths: "Novel approach with high potential impact",
        weaknesses: "Technical complexity may limit near-term clinical translation",
      },
    ],
    evolution_history: ["Initial hypothesis generated", "Added real-time control aspect"],
    similarity_cluster_id: "cluster_A",
    win_count: 9,
    loss_count: 6,
    total_matches: 15,
    win_rate: 0.6,
  },
  {
    text: "Cell-penetrating peptides conjugated to therapeutic agents bypass traditional membrane barriers for enhanced intracellular delivery",
    id: "hyp_003",
    score: 7.9,
    elo_rating: 1445,
    rank: 3,
    reviews: [
      {
        scores: {
          novelty: 3,
          scientific_validity: 5,
          feasibility: 5,
          specificity: 4,
          impact_potential: 3,
          clarity: 5,
        },
        review_summary: "Solid approach with proven track record",
        overall_score: 0.79,
        constructive_feedback: "Consider addressing immunogenicity concerns",
        strengths: "Well-established technology, high feasibility",
        weaknesses: "Lower novelty compared to other approaches",
      },
    ],
    evolution_history: ["Initial hypothesis generated"],
    win_count: 6,
    loss_count: 9,
    total_matches: 15,
    win_rate: 0.4,
  },
];
