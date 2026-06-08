import React from "react";
import type { AgentOutput } from "@/types/agents";
import { SupervisorAgent } from "./SupervisorAgent";
import { LiteratureReviewAgent } from "./LiteratureReviewAgent";
import { HypothesisGeneratorAgent } from "./HypothesisGeneratorAgent";
import { ReflectionAgent } from "./ReflectionAgent";
import { HypothesisReflectorAgent } from "./HypothesisReflectorAgent";
import { HypothesisRankerAgent } from "./HypothesisRankerAgent";
import { RankingJudgeAgent } from "./RankingJudgeAgent";
import { MetaReviewerAgent } from "./MetaReviewerAgent";
import { HypothesisEvolverAgent } from "./HypothesisEvolverAgent";
import { ProximityAnalyzerAgent } from "./ProximityAnalyzerAgent";
import { Card } from "@/components/ui/card";

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
