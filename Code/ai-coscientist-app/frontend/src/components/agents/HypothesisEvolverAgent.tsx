import { ArrowDown, ChevronDown, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useHypothesisFocus } from "@/context/HypothesisFocusContext";
import { cn } from "@/lib/utils";
import type { AgentOutput } from "@/types/agents";
import { getAgentColor } from "@/utils/agentFormatters";

export interface HypothesisEvolverAgentProps {
  output: AgentOutput;
}

export function HypothesisEvolverAgent({ output }: HypothesisEvolverAgentProps) {
  const [showDetails, setShowDetails] = useState(false);
  const { pinnedText, trackEvolution, isTracked } = useHypothesisFocus();
  const data = output.parsed;

  // register evolution chains so later nodes can match evolved hypothesis texts
  useEffect(() => {
    if (!pinnedText || !data?.evolution_details) return;
    for (const evo of data.evolution_details) {
      if (evo.original && evo.evolved) {
        trackEvolution(evo.original, evo.evolved);
      }
    }
  }, [pinnedText, data?.evolution_details]);

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <RefreshCw
          className="w-5 h-5 shrink-0 mt-0.5"
          style={{ color: getAgentColor("HypothesisEvolver") }}
        />
        <div className="flex-1 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <h4 className="font-semibold">Hypothesis Evolution</h4>
            <Badge variant="outline" className="text-xs">
              {new Date(output.timestamp).toLocaleTimeString()}
            </Badge>
          </div>

          {/* Refinement Summary */}
          {data?.refinement_summary && (
            <div className="p-3 bg-th-muted rounded border border-th-muted">
              <p className="text-sm font-medium">{data.refinement_summary}</p>
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
            {showDetails ? "Hide" : "Show"} Evolution Details
          </button>

          {/* Expanded Details */}
          {showDetails && (
            <div className="space-y-4">
              {/* Show all evolution details if available */}
              {data?.evolution_details &&
                Array.isArray(data.evolution_details) &&
                data.evolution_details.length > 0 && (
                  <div className="space-y-4">
                    {(pinnedText
                      ? data.evolution_details.filter((evo: any) => isTracked(evo.original || ""))
                      : data.evolution_details
                    ).map((evolution: any, index: number) => (
                      <div key={index} className="border-l-2 border-purple-500 pl-3 space-y-2">
                        <div className="text-sm font-medium text-purple-600">
                          Evolution {index + 1}
                        </div>

                        {/* Rationale */}
                        {evolution.rationale && (
                          <div className="text-sm text-muted-foreground">
                            <span className="font-medium">Rationale:</span> {evolution.rationale}
                          </div>
                        )}

                        {/* Original → Evolved */}
                        {evolution.original && evolution.evolved && (
                          <div className="space-y-2">
                            <div className="p-2 bg-th-secondary rounded text-xs">
                              <p className="text-muted-foreground mb-1 font-medium">Original:</p>
                              <p className="opacity-60">{evolution.original}</p>
                            </div>

                            <div className="flex justify-center">
                              <ArrowDown className="w-4 h-4 text-muted-foreground" />
                            </div>

                            <div className="p-2 bg-th-muted rounded border border-th-muted text-xs">
                              <p className="text-th-fg mb-1 font-medium">Evolved:</p>
                              <p>{evolution.evolved}</p>
                            </div>
                          </div>
                        )}

                        {/* Changes */}
                        {evolution.changes &&
                          Array.isArray(evolution.changes) &&
                          evolution.changes.length > 0 && (
                            <div>
                              <p className="text-xs font-medium text-muted-foreground mb-1">
                                Key Changes:
                              </p>
                              <ul className="list-disc list-inside space-y-1 text-xs text-muted-foreground ml-2">
                                {evolution.changes.map((change: string, i: number) => (
                                  <li key={i}>{change}</li>
                                ))}
                              </ul>
                            </div>
                          )}

                        {/* Improvements */}
                        {evolution.improvements &&
                          Array.isArray(evolution.improvements) &&
                          evolution.improvements.length > 0 && (
                            <div>
                              <p className="text-xs font-medium text-muted-foreground mb-1">
                                Improvements:
                              </p>
                              <ul className="list-disc list-inside space-y-1 text-xs text-muted-foreground ml-2">
                                {evolution.improvements.map((improvement: string, i: number) => (
                                  <li key={i}>{improvement}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                      </div>
                    ))}
                  </div>
                )}

              {/* Show message if no evolution data available */}
              {(!data?.evolution_details || data.evolution_details.length === 0) && (
                <p className="text-sm text-muted-foreground italic">
                  Evolution in progress or no data available
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
