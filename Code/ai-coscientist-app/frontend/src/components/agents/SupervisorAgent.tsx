import { ChevronDown, Star } from "lucide-react";
import React, { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { AgentOutput } from "@/types/agents";
import { getAgentColor } from "@/utils/agentFormatters";

export interface SupervisorAgentProps {
  output: AgentOutput;
}

/**
 * Display component for Supervisor agent output
 */
export function SupervisorAgent({ output }: SupervisorAgentProps) {
  const [showDetails, setShowDetails] = useState(false);
  const data = output.parsed;

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <Star className="w-5 h-5 shrink-0 mt-0.5" style={{ color: getAgentColor("Supervisor") }} />
        <div className="flex-1 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <h4 className="font-semibold">Research Supervisor</h4>
            <Badge variant="outline" className="text-xs">
              {new Date(output.timestamp).toLocaleTimeString()}
            </Badge>
          </div>

          {/* Summary */}
          {data?.research_goal_analysis?.goal_summary && (
            <p className="text-sm">{data.research_goal_analysis.goal_summary}</p>
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
              {/* Key Areas */}
              {data?.research_goal_analysis?.key_areas && (
                <div>
                  <h5 className="font-medium text-sm mb-2">Key Areas</h5>
                  <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                    {data.research_goal_analysis.key_areas.map((area: string, index: number) => (
                      <li key={index}>{area}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Constraints Identified */}
              {data?.research_goal_analysis?.constraints_identified && (
                <div>
                  <h5 className="font-medium text-sm mb-2">Constraints Identified</h5>
                  <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                    {data.research_goal_analysis.constraints_identified.map(
                      (constraint: string, index: number) => (
                        <li key={index}>{constraint}</li>
                      )
                    )}
                  </ul>
                </div>
              )}

              {/* Success Criteria */}
              {data?.research_goal_analysis?.success_criteria && (
                <div>
                  <h5 className="font-medium text-sm mb-2">Success Criteria</h5>
                  <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                    {data.research_goal_analysis.success_criteria.map(
                      (criterion: string, index: number) => (
                        <li key={index}>{criterion}</li>
                      )
                    )}
                  </ul>
                </div>
              )}

              {/* Workflow Plan */}
              {data?.workflow_plan && (
                <div>
                  <h5 className="font-medium text-sm mb-2">Workflow Plan</h5>
                  <div className="space-y-3 text-sm">
                    {/* Generation Phase */}
                    {data.workflow_plan.generation_phase && (
                      <div className="space-y-2">
                        <div className="font-medium text-foreground">Generation Phase</div>
                        {data.workflow_plan.generation_phase.quantity_target && (
                          <div className="text-muted-foreground">
                            <span className="font-medium">Quantity Target:</span>{" "}
                            {data.workflow_plan.generation_phase.quantity_target}
                          </div>
                        )}
                        {data.workflow_plan.generation_phase.diversity_targets && (
                          <div className="text-muted-foreground">
                            <span className="font-medium">Diversity Targets:</span>{" "}
                            {data.workflow_plan.generation_phase.diversity_targets}
                          </div>
                        )}
                        {data.workflow_plan.generation_phase.focus_areas && (
                          <div>
                            <div className="font-medium text-muted-foreground mb-1">
                              Focus Areas:
                            </div>
                            <ul className="list-disc list-inside space-y-1 text-muted-foreground ml-2">
                              {data.workflow_plan.generation_phase.focus_areas.map(
                                (area: string, index: number) => (
                                  <li key={index}>{area}</li>
                                )
                              )}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Review Phase */}
                    {data.workflow_plan.review_phase && (
                      <div className="space-y-2">
                        <div className="font-medium text-foreground">Review Phase</div>
                        {data.workflow_plan.review_phase.critical_criteria && (
                          <div>
                            <div className="font-medium text-muted-foreground mb-1">
                              Critical Criteria:
                            </div>
                            <ul className="list-disc list-inside space-y-1 text-muted-foreground ml-2">
                              {data.workflow_plan.review_phase.critical_criteria.map(
                                (criterion: string, index: number) => (
                                  <li key={index}>{criterion}</li>
                                )
                              )}
                            </ul>
                          </div>
                        )}
                        {data.workflow_plan.review_phase.review_depth && (
                          <div className="text-muted-foreground">
                            <span className="font-medium">Review Depth:</span>{" "}
                            {data.workflow_plan.review_phase.review_depth}
                          </div>
                        )}
                        {data.workflow_plan.review_phase.reviews_per_hypothesis && (
                          <div className="text-muted-foreground">
                            <span className="font-medium">Reviews per Hypothesis:</span>{" "}
                            {data.workflow_plan.review_phase.reviews_per_hypothesis}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Ranking Phase */}
                    {data.workflow_plan.ranking_phase && (
                      <div className="space-y-2">
                        <div className="font-medium text-foreground">Ranking Phase</div>
                        {data.workflow_plan.ranking_phase.ranking_approach && (
                          <div className="text-muted-foreground">
                            <span className="font-medium">Ranking Approach:</span>{" "}
                            {data.workflow_plan.ranking_phase.ranking_approach}
                          </div>
                        )}
                        {data.workflow_plan.ranking_phase.selection_criteria && (
                          <div>
                            <div className="font-medium text-muted-foreground mb-1">
                              Selection Criteria:
                            </div>
                            <ul className="list-disc list-inside space-y-1 text-muted-foreground ml-2">
                              {data.workflow_plan.ranking_phase.selection_criteria.map(
                                (criterion: string, index: number) => (
                                  <li key={index}>{criterion}</li>
                                )
                              )}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Evolution Phase */}
                    {data.workflow_plan.evolution_phase && (
                      <div className="space-y-2">
                        <div className="font-medium text-foreground">Evolution Phase</div>
                        {data.workflow_plan.evolution_phase.refinement_priorities && (
                          <div>
                            <div className="font-medium text-muted-foreground mb-1">
                              Refinement Priorities:
                            </div>
                            <ul className="list-disc list-inside space-y-1 text-muted-foreground ml-2">
                              {data.workflow_plan.evolution_phase.refinement_priorities.map(
                                (priority: string, index: number) => (
                                  <li key={index}>{priority}</li>
                                )
                              )}
                            </ul>
                          </div>
                        )}
                        {data.workflow_plan.evolution_phase.iteration_strategy && (
                          <div className="text-muted-foreground">
                            <span className="font-medium">Iteration Strategy:</span>{" "}
                            {data.workflow_plan.evolution_phase.iteration_strategy}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Performance Assessment */}
              {data?.performance_assessment && (
                <div>
                  <h5 className="font-medium text-sm mb-2">Performance Assessment</h5>
                  <div className="space-y-2 text-sm text-muted-foreground">
                    {data.performance_assessment.current_status && (
                      <div>
                        <span className="font-medium">Current Status:</span>{" "}
                        {data.performance_assessment.current_status}
                      </div>
                    )}
                    {data.performance_assessment.bottlenecks_identified && (
                      <div>
                        <div className="font-medium mb-1">Bottlenecks Identified:</div>
                        <ul className="list-disc list-inside space-y-1 ml-2">
                          {data.performance_assessment.bottlenecks_identified.map(
                            (bottleneck: string, index: number) => (
                              <li key={index}>{bottleneck}</li>
                            )
                          )}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Adjustment Recommendations */}
              {data?.adjustment_recommendations && data.adjustment_recommendations.length > 0 && (
                <div>
                  <h5 className="font-medium text-sm mb-2">Adjustment Recommendations</h5>
                  <div className="space-y-3 text-sm text-muted-foreground">
                    {data.adjustment_recommendations.map((rec: any, index: number) => (
                      <div key={index} className="space-y-1">
                        <div className="font-medium text-foreground">{rec.aspect}</div>
                        <div>
                          <span className="font-medium">Adjustment:</span> {rec.adjustment}
                        </div>
                        {rec.justification && (
                          <div>
                            <span className="font-medium">Justification:</span> {rec.justification}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Output Preparation */}
              {data?.output_preparation && (
                <div>
                  <h5 className="font-medium text-sm mb-2">Output Preparation</h5>
                  <div className="space-y-2 text-sm text-muted-foreground">
                    {data.output_preparation.hypothesis_selection_strategy && (
                      <div>
                        <span className="font-medium">Selection Strategy:</span>{" "}
                        {data.output_preparation.hypothesis_selection_strategy}
                      </div>
                    )}
                    {data.output_preparation.presentation_format && (
                      <div>
                        <span className="font-medium">Presentation Format:</span>{" "}
                        {data.output_preparation.presentation_format}
                      </div>
                    )}
                    {data.output_preparation.key_insights_to_highlight && (
                      <div>
                        <div className="font-medium mb-1">Key Insights to Highlight:</div>
                        <ul className="list-disc list-inside space-y-1 ml-2">
                          {data.output_preparation.key_insights_to_highlight.map(
                            (insight: string, index: number) => (
                              <li key={index}>{insight}</li>
                            )
                          )}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
