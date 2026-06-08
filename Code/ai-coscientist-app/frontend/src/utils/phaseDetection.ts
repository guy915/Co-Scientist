import type { AgentOutput, AgentGroup } from "@/types/agents";
import { formatAgentName } from "./agentFormatters";

export interface PhaseInfo {
  id: string;
  name: string;
  color: string;
  icon: string;
  agents: AgentOutput[];
  agentCount: number;
  summary: string;
}

/**
 * Get theme-aware phase color using CSS variables
 */
function getPhaseColor(phaseIndex: number): string {
  // Map to phase0-4 CSS variables (th- prefix for theme colors)
  const colorIndex = phaseIndex % 5;
  return `var(--color-th-phase${colorIndex})`;
}

/**
 * Group agent outputs by workflow phase
 */
export function groupByPhase(outputs: AgentOutput[]): PhaseInfo[] {
  const groups: { [key: string]: PhaseInfo } = {};

  outputs.forEach((output) => {
    let phaseKey = "initial_generation";
    let phaseName = "Initial Generation";
    let phaseColor = getPhaseColor(0);
    let phaseIcon = "Sparkles";

    // Detect phase/iteration from output metadata
    const iteration = output.iteration ?? 0;

    if (iteration === 0) {
      // Initial generation phase (includes ranking tournament)
      phaseKey = "initial_generation";
      phaseName = "Initial Generation";
      phaseColor = getPhaseColor(0);
      phaseIcon = "Sparkles";
    } else {
      // Iteration phases (1, 2, 3...)
      phaseKey = `iteration_${iteration}`;
      phaseName = `Iteration ${iteration}`;
      phaseColor = getPhaseColor(iteration);
      phaseIcon = "RefreshCw";
    }

    // Create phase group if not exists
    if (!groups[phaseKey]) {
      groups[phaseKey] = {
        id: phaseKey,
        name: phaseName,
        color: phaseColor,
        icon: phaseIcon,
        agents: [],
        agentCount: 0,
        summary: "",
      };
    }

    groups[phaseKey].agents.push(output);
  });

  // Generate summaries for each phase
  Object.values(groups).forEach((group) => {
    const nonMarkerAgents = group.agents.filter((a) => !a.isPhaseMarker);
    group.agentCount = nonMarkerAgents.length;

    const agentCounts: { [key: string]: number } = {};
    nonMarkerAgents.forEach((agent) => {
      agentCounts[agent.name] = (agentCounts[agent.name] || 0) + 1;
    });

    const summaryParts: string[] = [];
    Object.entries(agentCounts).forEach(([name, count]) => {
      if (count > 1) {
        summaryParts.push(`${count}× ${formatAgentName(name)}`);
      } else {
        summaryParts.push(formatAgentName(name));
      }
    });

    group.summary = summaryParts.slice(0, 3).join(", ") + (summaryParts.length > 3 ? "..." : "");
  });

  return Object.values(groups);
}

/**
 * Group agents by type (for collapsing similar agents)
 */
export function groupAgentsByType(agents: AgentOutput[]): (AgentOutput | AgentGroup)[] {
  const result: (AgentOutput | AgentGroup)[] = [];
  const grouped: { [key: string]: AgentOutput[] } = {};

  agents.forEach((agent) => {
    if (agent.isPhaseMarker) {
      // Skip phase markers
    } else if (agent.name === "HypothesisReflector" || agent.name === "RankingJudge") {
      if (!grouped[agent.name]) {
        grouped[agent.name] = [];
      }
      grouped[agent.name].push(agent);
    } else {
      result.push(agent);
    }
  });

  // Add grouped agents - always group HypothesisReflector and RankingJudge
  Object.entries(grouped).forEach(([name, groupedAgents]) => {
    // Always create group (even for single items)
    let summary = "";
    if (name === "HypothesisReflector") {
      // Extract all scores from all_reviews arrays
      const scores: number[] = [];
      let totalReviews = 0;
      groupedAgents.forEach((a) => {
        if (a.parsed?.all_reviews && Array.isArray(a.parsed.all_reviews)) {
          // Extract scores from all_reviews array
          a.parsed.all_reviews.forEach((review: any) => {
            if (review.overall_score !== undefined) {
              scores.push(review.overall_score);
              totalReviews++;
            }
          });
        } else if (a.parsed?.overall_score !== undefined) {
          // Fallback for single review format
          scores.push(a.parsed.overall_score);
          totalReviews++;
        }
      });
      // Scores are 1-10, convert to percentage by multiplying by 10 (not 100!)
      const avgScore =
        scores.length > 0
          ? ((scores.reduce((a, b) => a + b, 0) / scores.length) * 10).toFixed(1)
          : "N/A";
      summary = `${totalReviews} peer review${totalReviews !== 1 ? "s" : ""} (avg: ${avgScore}%)`;
    }

    result.push({
      name,
      agents: groupedAgents,
      summary,
    });
  });

  // Sort by timestamp
  result.sort((a, b) => {
    const aTime = "timestamp" in a ? a.timestamp : a.agents[0].timestamp;
    const bTime = "timestamp" in b ? b.timestamp : b.agents[0].timestamp;
    return aTime - bTime;
  });

  return result;
}
