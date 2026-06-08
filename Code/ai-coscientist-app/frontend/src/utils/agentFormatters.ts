import {
  Star,
  Sparkles,
  Eye,
  BarChart3,
  Trophy,
  BookOpen,
  RefreshCw,
  Network,
  Settings,
  Lightbulb,
  type LucideIcon,
} from "lucide-react";
import { resolveTemplate } from "./domainResolver";
import type { DomainConfig } from "@/domains/types";

/**
 * Get the icon component for a given agent name
 */
export function getAgentIcon(agentName: string): LucideIcon {
  const iconMap: Record<string, LucideIcon> = {
    Supervisor: Star,
    HypothesisGenerator: Sparkles,
    Reflection: Lightbulb,
    HypothesisReflector: Eye,
    HypothesisRanker: BarChart3,
    RankingJudge: Trophy, // TBD if we change this
    MetaReviewer: BookOpen,
    HypothesisEvolver: RefreshCw,
    ProximityAnalyzer: Network,
  };
  return iconMap[agentName] || Settings;
}

/**
 * Get the color for a given agent name (theme-aware)
 * Uses vibrant colors that maintain good contrast in both light and dark modes
 */
export function getAgentColor(agentName: string): string {
  const colorMap: Record<string, string> = {
    Supervisor: "var(--color-th-warning)", // gold/orange
    HypothesisGenerator: "var(--color-th-phase1)", // purple
    Reflection: "var(--color-th-phase2)", // orange/amber
    HypothesisReflector: "var(--color-th-info)", // cyan/blue
    HypothesisRanker: "var(--color-th-success)", // green
    RankingJudge: "var(--color-th-destructive)", // red
    MetaReviewer: "var(--color-th-phase4)", // violet/indigo
    HypothesisEvolver: "var(--color-th-phase0)", // green
    ProximityAnalyzer: "var(--color-th-info)", // cyan/blue
    LiteratureReview: "var(--color-th-link)", // blue
  };
  return colorMap[agentName] || "var(--color-th-fg)";
}

/**
 * Format agent name for display using domain configuration
 * Falls back to hardcoded names if domain config not provided or agent not found
 */
export function formatAgentName(agentName: string, config?: DomainConfig): string {
  // use domain config if provided
  if (config?.agents && agentName in config.agents) {
    return resolveTemplate(config.agents[agentName], config);
  }

  // fallback to hardcoded names (for backwards compatibility)
  const nameMap: Record<string, string> = {
    Supervisor: "Research Supervisor",
    HypothesisGenerator: "Hypothesis Generator",
    Reflection: "Reflection Observations",
    HypothesisReflector: "Peer Reviewer",
    HypothesisRanker: "Hypothesis Ranker",
    RankingJudge: "Ranking Judge",
    MetaReviewer: "Meta Reviewer",
    HypothesisEvolver: "Hypothesis Evolver",
    ProximityAnalyzer: "Proximity Analyzer",
  };
  return nameMap[agentName] || agentName;
}
