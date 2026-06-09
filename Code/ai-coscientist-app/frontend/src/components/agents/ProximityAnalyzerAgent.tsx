import { Network } from "lucide-react";
import React from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { AgentOutput } from "@/types/agents";
import { getAgentColor } from "@/utils/agentFormatters";

export interface ProximityAnalyzerAgentProps {
  output: AgentOutput;
}

export function ProximityAnalyzerAgent({ output }: ProximityAnalyzerAgentProps) {
  const data = output.parsed;
  const clusters = data?.similarity_clusters || [];

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <Network
          className="w-5 h-5 shrink-0 mt-0.5"
          style={{ color: getAgentColor("ProximityAnalyzer") }}
        />
        <div className="flex-1 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <h4 className="font-semibold">Deduplication Analysis</h4>
            <Badge variant="outline" className="text-xs">
              {new Date(output.timestamp).toLocaleTimeString()}
            </Badge>
          </div>

          <div className="flex items-center gap-4 text-sm">
            <div>
              <span className="font-medium">{clusters.length}</span>{" "}
              <span className="text-muted-foreground">clusters identified</span>
            </div>
          </div>

          {data?.diversity_assessment && (
            <p className="text-sm text-muted-foreground">{data.diversity_assessment}</p>
          )}

          {clusters.length > 0 && (
            <div className="space-y-2">
              <h5 className="font-medium text-sm">Clusters</h5>
              {clusters.map((cluster: any, index: number) => (
                <div key={index} className="p-2 bg-th-muted rounded text-sm">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant="secondary" className="text-xs">
                      Cluster {cluster.cluster_id || index + 1}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {cluster.hypotheses?.length || 0} hypotheses
                    </span>
                  </div>
                  {cluster.similarity_score !== undefined && (
                    <span className="text-xs text-muted-foreground">
                      Similarity: {(cluster.similarity_score * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
