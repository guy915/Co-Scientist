import { BarChart3, ChevronDown, ChevronUp } from "lucide-react";
import React, { useState } from "react";
import { HypothesisDetails } from "@/components/hypothesis/HypothesisDetails";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useHypothesisFocus } from "@/context/HypothesisFocusContext";
import type { AgentOutput } from "@/types/agents";
import { getAgentColor } from "@/utils/agentFormatters";
import { isTrackedHypothesis } from "@/utils/hypothesisFocus";

export interface HypothesisRankerAgentProps {
  output: AgentOutput;
}

export function HypothesisRankerAgent({ output }: HypothesisRankerAgentProps) {
  const [expandedHypotheses, setExpandedHypotheses] = useState<Set<number>>(new Set());
  const { pinnedText, isTracked } = useHypothesisFocus();
  const data = output.parsed;
  const allRanked = data?.ranked_hypotheses || [];
  const rankedHypotheses = pinnedText
    ? allRanked.filter(
        (hyp: any) =>
          isTracked(hyp.text || "") ||
          isTracked(hyp.hypothesis || "") ||
          isTrackedHypothesis(hyp, pinnedText)
      )
    : allRanked;

  const toggleHypothesis = (index: number) => {
    const newExpanded = new Set(expandedHypotheses);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpandedHypotheses(newExpanded);
  };

  // determine phase label
  let phaseLabel = "";
  if (output.iteration !== undefined && output.iteration > 0) {
    phaseLabel = ` (Iteration ${output.iteration})`;
  } else if (output.phase === "initial_generation") {
    phaseLabel = " (Initial)";
  }

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <BarChart3
          className="w-5 h-5 shrink-0 mt-0.5"
          style={{ color: getAgentColor("HypothesisRanker") }}
        />
        <div className="flex-1 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <h4 className="font-semibold">
              Ranked {allRanked.length} Hypotheses{phaseLabel}
              {pinnedText && (
                <span className="ml-2 text-xs font-normal text-th-muted-fg">
                  (showing 1 of {allRanked.length})
                </span>
              )}
            </h4>
            <Badge variant="outline" className="text-xs">
              {new Date(output.timestamp).toLocaleTimeString()}
            </Badge>
          </div>

          <div className="space-y-3">
            {(pinnedText ? rankedHypotheses : rankedHypotheses.slice(0, 5)).map(
              (hyp: any, index: number) => {
                const isExpanded = expandedHypotheses.has(index);
                const hasDetails = hyp.explanation || hyp.literature_grounding || hyp.experiment;

                return (
                  <div key={index} className="border rounded-md p-3 bg-th-muted">
                    <div className="flex items-start gap-2 mb-2">
                      <Badge variant="secondary" className="text-xs shrink-0">
                        #{index + 1}
                      </Badge>
                      {hyp.overall_score !== undefined && (
                        <Badge variant="outline" className="text-xs">
                          Score: {(hyp.overall_score * 100).toFixed(0)}%
                        </Badge>
                      )}
                    </div>

                    {!isExpanded && (
                      <div>
                        <p className="text-sm text-th-fg leading-relaxed">{hyp.text}</p>
                        {hasDetails && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => toggleHypothesis(index)}
                            className="mt-2 h-7 text-xs"
                          >
                            <ChevronDown className="w-3 h-3 mr-1" />
                            Show Details
                          </Button>
                        )}
                      </div>
                    )}

                    {isExpanded && (
                      <div>
                        <HypothesisDetails hypothesis={hyp} showAllFields={true} />
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => toggleHypothesis(index)}
                          className="mt-2 h-7 text-xs"
                        >
                          <ChevronUp className="w-3 h-3 mr-1" />
                          Hide Details
                        </Button>
                      </div>
                    )}

                    {hyp.overall_score !== undefined && (
                      <div className="mt-2">
                        <Progress value={hyp.overall_score * 100} className="h-1" />
                      </div>
                    )}
                  </div>
                );
              }
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
