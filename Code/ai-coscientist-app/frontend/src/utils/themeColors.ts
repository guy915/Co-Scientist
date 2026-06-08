/**
 * helper to get theme-aware color for agent icons and UI elements
 * Uses vibrant colors that maintain good contrast in both light and dark modes
 */

export function getAgentIconColor(agentName: string): string {
  // map agents to theme color variables (th- prefix)
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

export const themeColors = {
  link: "var(--color-th-link)",
  linkHover: "var(--color-th-link-hover)",
  success: "var(--color-th-success)",
  warning: "var(--color-th-warning)",
  error: "var(--color-th-destructive)",
  info: "var(--color-th-info)",
  muted: "var(--color-th-muted)",
  mutedForeground: "var(--color-th-muted-fg)",
  primary: "var(--color-th-primary)",
  accent: "var(--color-th-accent)",
  bg: "var(--color-th-bg)",
  fg: "var(--color-th-fg)",
  card: "var(--color-th-card)",
  cardFg: "var(--color-th-card-fg)",
  secondary: "var(--color-th-secondary)",
  secondaryFg: "var(--color-th-secondary-fg)",
};
