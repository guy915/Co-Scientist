import React, { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { AgentGroup as AgentGroupType } from "@/types/agents";
import { getAgentIcon, getAgentColor, formatAgentName } from "@/utils/agentFormatters";
import { cn } from "@/lib/utils";
import { AgentDisplay } from "@/components/agents/AgentDisplay";
import { useDomain } from "@/context/DomainContext";

export interface AgentGroupProps {
  group: AgentGroupType;
}

/**
 * Collapsible group for multiple instances of the same agent
 */
export function AgentGroup({ group }: AgentGroupProps) {
  const { config } = useDomain();
  const [isExpanded, setIsExpanded] = useState(false);
  const Icon = getAgentIcon(group.name);
  const color = getAgentColor(group.name);
  const displayName = formatAgentName(group.name, config);

  // Helper to generate item summaries for collapsed state
  const getItemSummaries = () => {
    if (group.name === "HypothesisReflector") {
      // Each agent may have all_reviews array, so flatten them
      const allReviewItems: any[] = [];
      group.agents.forEach((agent) => {
        const iteration = agent.iteration;
        let iterationLabel = "";
        if (iteration !== undefined && iteration > 0) {
          iterationLabel = ` (Iteration ${iteration})`;
        } else if (iteration === 0) {
          iterationLabel = " (Initial)";
        }

        if (agent.parsed?.all_reviews && Array.isArray(agent.parsed.all_reviews)) {
          // This agent has multiple reviews
          agent.parsed.all_reviews.forEach((review: any, index: number) => {
            const score = review.overall_score;
            const scoreDisplay = score ? `${(score * 10).toFixed(0)}%` : "N/A";
            const hypothesisNum = review.hypothesis_index ?? index;
            allReviewItems.push({
              label: `Review #${hypothesisNum + 1}${iterationLabel}`,
              value: scoreDisplay,
              color: score && score >= 7 ? "text-th-success" : "text-th-muted-fg",
              score,
            });
          });
        } else {
          // Single review format (fallback)
          const score = agent.parsed?.overall_score;
          const scoreDisplay = score ? `${(score * 10).toFixed(0)}%` : "N/A";
          const hypothesisNum = agent.parsed?.hypothesis_index ?? allReviewItems.length;
          allReviewItems.push({
            label: `Review #${hypothesisNum + 1}${iterationLabel}`,
            value: scoreDisplay,
            color: score && score >= 7 ? "text-th-success" : "text-th-muted-fg",
            score,
          });
        }
      });
      return allReviewItems;
    } else if (group.name === "RankingJudge") {
      const allMatchups: any[] = [];
      group.agents.forEach((agent) => {
        const matchups = agent.parsed?.matchups || [];
        matchups.forEach((matchup: any) => {
          const winner = matchup.winner?.toUpperCase() || "N/A";
          allMatchups.push({
            label: `Ranking Judge ${allMatchups.length + 1}`,
            value: `Winner: ${winner}`,
            color: "text-th-link",
          });
        });
      });
      return allMatchups;
    }
    return [];
  };

  const itemSummaries = getItemSummaries();

  return (
    <Card className="overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3 flex items-center justify-between gap-3 hover:bg-th-muted transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <Icon className="w-5 h-5" style={{ color }} />
          <span className="font-medium">{displayName}</span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">{group.summary}</span>
          <ChevronRight className={cn("w-4 h-4 transition-transform", isExpanded && "rotate-90")} />
        </div>
      </button>

      {/* Collapsed Preview - Show item summaries */}
      {!isExpanded && itemSummaries.length > 0 && (
        <div className="px-4 pb-3 space-y-1.5">
          {itemSummaries.map((item, index) => (
            <div key={index} className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{item.label}</span>
              <Badge variant="outline" className={cn("font-medium", item.color)}>
                {item.value}
              </Badge>
            </div>
          ))}
        </div>
      )}

      {/* Expanded Content */}
      {isExpanded && (
        <div className="px-4 pb-4 space-y-2">
          {group.agents.map((agent, index) => (
            <div key={index}>
              <AgentDisplay output={agent} />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
