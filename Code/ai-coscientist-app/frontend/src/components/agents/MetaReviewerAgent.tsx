import { BookOpen, ChevronDown } from "lucide-react";
import React, { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { AgentOutput } from "@/types/agents";
import { getAgentColor } from "@/utils/agentFormatters";

export interface MetaReviewerAgentProps {
  output: AgentOutput;
}

export function MetaReviewerAgent({ output }: MetaReviewerAgentProps) {
  const [showDetails, setShowDetails] = useState(false);
  const data = output.parsed;

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <BookOpen
          className="w-5 h-5 shrink-0 mt-0.5"
          style={{ color: getAgentColor("MetaReviewer") }}
        />
        <div className="flex-1 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <h4 className="font-semibold">Meta Review</h4>
            <Badge variant="outline" className="text-xs">
              {new Date(output.timestamp).toLocaleTimeString()}
            </Badge>
          </div>

          {/* Summary */}
          {data?.summary && (
            <div>
              <p className="text-sm text-muted-foreground">{data.summary}</p>
            </div>
          )}

          {/* Details Toggle */}
          <button
            onClick={() => setShowDetails(!showDetails)}
            className="text-sm text-th-link hover:text-th-link-hover flex items-center gap-1"
          >
            <ChevronDown
              className={cn("w-4 h-4 transition-transform", showDetails && "rotate-180")}
            />
            {showDetails ? "Hide" : "Show"} Details
          </button>

          {/* Expanded Details */}
          {showDetails && (
            <div className="space-y-4 pt-2 border-t">
              {/* Common Strengths - can be string or array */}
              {data?.common_strengths &&
                Array.isArray(data.common_strengths) &&
                data.common_strengths.length > 0 && (
                  <div>
                    <h5 className="font-medium text-sm mb-1 text-th-success">Common Strengths</h5>
                    {Array.isArray(data.common_strengths) && data.common_strengths.length > 0 ? (
                      <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                        {data.common_strengths.map((strength: string, index: number) => (
                          <li key={index}>{strength}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-muted-foreground">{data.common_strengths}</p>
                    )}
                  </div>
                )}

              {/* Common Weaknesses - can be string or array */}
              {data?.common_weaknesses &&
                Array.isArray(data.common_weaknesses) &&
                data.common_weaknesses.length > 0 && (
                  <div>
                    <h5 className="font-medium text-sm mb-1 text-th-destructive">
                      Common Weaknesses
                    </h5>
                    {Array.isArray(data.common_weaknesses) ? (
                      <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                        {data.common_weaknesses.map((weakness: string, index: number) => (
                          <li key={index}>{weakness}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-muted-foreground">{data.common_weaknesses}</p>
                    )}
                  </div>
                )}

              {/* Strategic Recommendations */}
              {data?.strategic_recommendations &&
                Array.isArray(data.strategic_recommendations) &&
                data.strategic_recommendations.length > 0 && (
                  <div>
                    <h5 className="font-medium text-sm mb-2">Strategic Recommendations</h5>
                    <div className="space-y-3">
                      {data.strategic_recommendations.map((rec: any, index: number) => (
                        <div key={index} className="border-l-2 border-blue-500 pl-3 space-y-1">
                          {/* Handle both string and object formats */}
                          {typeof rec === "string" ? (
                            <p className="text-sm text-muted-foreground">{rec}</p>
                          ) : (
                            <>
                              {rec.focus_area && (
                                <div className="text-sm font-medium text-foreground">
                                  {rec.focus_area}
                                </div>
                              )}
                              {rec.recommendation && (
                                <div className="text-sm text-muted-foreground">
                                  <span className="font-medium">Recommendation:</span>{" "}
                                  {rec.recommendation}
                                </div>
                              )}
                              {rec.justification && (
                                <div className="text-sm text-muted-foreground italic">
                                  <span className="font-medium">Justification:</span>{" "}
                                  {rec.justification}
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

              {/* Emerging Themes */}
              {data?.emerging_themes &&
                Array.isArray(data.emerging_themes) &&
                data.emerging_themes.length > 0 && (
                  <div>
                    <h5 className="font-medium text-sm mb-2">Emerging Themes</h5>
                    <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                      {data.emerging_themes.map((theme: string, index: number) => (
                        <li key={index}>{theme}</li>
                      ))}
                    </ul>
                  </div>
                )}

              {/* Areas for Improvement */}
              {data?.areas_for_improvement &&
                Array.isArray(data.areas_for_improvement) &&
                data.areas_for_improvement.length > 0 && (
                  <div>
                    <h5 className="font-medium text-sm mb-2">Areas for Improvement</h5>
                    <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                      {data.areas_for_improvement.map((area: string, index: number) => (
                        <li key={index}>{area}</li>
                      ))}
                    </ul>
                  </div>
                )}

              {/* Diversity Assessment */}
              {data?.diversity_assessment && data.diversity_assessment.trim() && (
                <div>
                  <h5 className="font-medium text-sm mb-2">Diversity Assessment</h5>
                  <p className="text-sm text-muted-foreground">{data.diversity_assessment}</p>
                </div>
              )}

              {/* Top Performers Analysis */}
              {data?.top_performers_analysis && data.top_performers_analysis.trim() && (
                <div>
                  <h5 className="font-medium text-sm mb-2">Top Performers Analysis</h5>
                  <p className="text-sm text-muted-foreground">{data.top_performers_analysis}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
