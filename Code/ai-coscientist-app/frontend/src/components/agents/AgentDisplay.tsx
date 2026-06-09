import React from "react";
import { Card } from "@/components/ui/card";
import type { AgentOutput } from "@/types/agents";
import { HypothesisEvolverAgent } from "./HypothesisEvolverAgent";
import { HypothesisGeneratorAgent } from "./HypothesisGeneratorAgent";
import { HypothesisRankerAgent } from "./HypothesisRankerAgent";
import { HypothesisReflectorAgent } from "./HypothesisReflectorAgent";
import { LiteratureReviewAgent } from "./LiteratureReviewAgent";
import { MetaReviewerAgent } from "./MetaReviewerAgent";
import { ProximityAnalyzerAgent } from "./ProximityAnalyzerAgent";
import { RankingJudgeAgent } from "./RankingJudgeAgent";
import { ReflectionAgent } from "./ReflectionAgent";
import { SupervisorAgent } from "./SupervisorAgent";

export interface AgentDisplayProps {
  output: AgentOutput;
}

/**
 * Router component that renders the appropriate agent-specific display
 */
export function AgentDisplay({ output }: AgentDisplayProps) {
  try {
    switch (output.name) {
      case "Supervisor":
        return <SupervisorAgent output={output} />;
      case "LiteratureReview":
        return <LiteratureReviewAgent output={output} />;
      case "HypothesisGenerator":
        return <HypothesisGeneratorAgent output={output} />;
      case "Reflection":
        return <ReflectionAgent output={output} />;
      case "HypothesisReflector":
        return <HypothesisReflectorAgent output={output} />;
      case "HypothesisRanker":
        return <HypothesisRankerAgent output={output} />;
      case "RankingJudge":
        return <RankingJudgeAgent output={output} />;
      case "MetaReviewer":
        return <MetaReviewerAgent output={output} />;
      case "HypothesisEvolver":
        return <HypothesisEvolverAgent output={output} />;
      case "ProximityAnalyzer":
        return <ProximityAnalyzerAgent output={output} />;
      default:
        // Fallback: show raw JSON
        return (
          <Card className="p-4">
            <h4 className="font-semibold mb-2">{output.name}</h4>
            <pre className="text-xs overflow-auto bg-th-muted p-3 rounded">{output.content}</pre>
          </Card>
        );
    }
  } catch (error) {
    console.error("Error rendering agent display:", error);
    return (
      <Card className="p-4 border-th-destructive">
        <p className="text-th-destructive text-sm">Error displaying {output.name}</p>
      </Card>
    );
  }
}
