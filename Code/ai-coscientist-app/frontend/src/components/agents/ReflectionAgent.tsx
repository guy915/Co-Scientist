import { ChevronDown, ChevronRight, Lightbulb } from "lucide-react";
import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import { DomainCustomFields } from "@/components/hypothesis/DomainCustomFields";
import { HypothesisDetails } from "@/components/hypothesis/HypothesisDetails";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useHypothesisFocus } from "@/context/HypothesisFocusContext";
import { cn } from "@/lib/utils";
import type { AgentOutput } from "@/types/agents";
import { getAgentColor } from "@/utils/agentFormatters";
import { isTrackedHypothesis } from "@/utils/hypothesisFocus";

export interface ReflectionAgentProps {
  output: AgentOutput;
}

/**
 * get badge variant based on classification
 */
function getBadgeVariant(classification: string) {
  const lower = classification.toLowerCase();
  if (lower.includes("missing piece")) return "success";
  if (lower.includes("disproved")) return "destructive";
  if (lower.includes("neutral")) return "secondary";
  return "default";
}

/**
 * display component for reflection agent output
 * analyzes hypotheses against literature observations
 */
export function ReflectionAgent({ output }: ReflectionAgentProps) {
  const [showDetails, setShowDetails] = useState(false);
  const { pinnedText, isTracked } = useHypothesisFocus();
  const data = output.parsed;
  const hypotheses = data?.hypotheses || [];

  // filter hypotheses that have reflection notes
  const hypothesesWithReflection = hypotheses
    .map((hyp: any, originalIndex: number) => ({ hyp, originalIndex }))
    .filter(({ hyp }: { hyp: any; originalIndex: number }) => hyp.reflection_notes)
    .filter(
      ({ hyp }: { hyp: any; originalIndex: number }) =>
        !pinnedText ||
        isTracked(hyp.text || "") ||
        isTracked(hyp.hypothesis || "") ||
        isTrackedHypothesis(hyp, pinnedText)
    );

  if (hypothesesWithReflection.length === 0) {
    return (
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <Lightbulb
            className="w-5 h-5 shrink-0 mt-0.5"
            style={{ color: getAgentColor("Reflection") }}
          />
          <div className="flex-1 space-y-3">
            <div className="flex items-start justify-between gap-2">
              <h4 className="font-semibold">Reflection Observations</h4>
              <Badge variant="outline" className="text-xs">
                {new Date(output.timestamp).toLocaleTimeString()}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              Analyzing hypotheses against literature observations...
            </p>
          </div>
        </div>
      </Card>
    );
  }

  // parse classifications for all reflections
  const reflectionSummaries = hypothesesWithReflection.map(
    ({ hyp, originalIndex }: { hyp: any; originalIndex: number }) => {
      const classificationMatch = hyp.reflection_notes?.match(/Classification:\s*(.+?)(?:\n|$)/i);
      const classification = classificationMatch ? classificationMatch[1].trim() : "neutral";
      return { hypothesisNumber: originalIndex + 1, classification, hypothesis: hyp };
    }
  );

  return (
    <Card className="p-0 overflow-hidden">
      {/* Clickable header */}
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="w-full px-4 py-3 flex items-center justify-between gap-3 hover:bg-th-muted transition-colors text-left"
      >
        <div className="flex items-start gap-3 flex-1">
          <Lightbulb
            className="w-5 h-5 shrink-0 mt-0.5"
            style={{ color: getAgentColor("Reflection") }}
          />
          <div className="flex-1">
            <h4 className="font-semibold">
              Reflection Observations ({hypothesesWithReflection.length} Hypotheses)
            </h4>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs">
            {new Date(output.timestamp).toLocaleTimeString()}
          </Badge>
          <ChevronRight
            className={cn(
              "w-4 h-4 transition-transform text-th-muted-fg",
              showDetails && "rotate-90"
            )}
          />
        </div>
      </button>

      {/* Content area */}
      <div className="px-4 pb-4">
        {/* Compact summary - always visible */}
        {!showDetails && (
          <div className="space-y-2 pt-3">
            {reflectionSummaries.map((item) => (
              <div key={item.hypothesisNumber} className="flex items-center gap-2">
                <span className="text-sm">Reflection {item.hypothesisNumber}</span>
                <Badge variant={getBadgeVariant(item.classification) as any} className="text-xs">
                  {item.classification}
                </Badge>
              </div>
            ))}
          </div>
        )}

        {/* Detailed view - expanded */}
        {showDetails && (
          <div className="space-y-3 pt-3">
            {hypothesesWithReflection.map(
              ({ hyp, originalIndex }: { hyp: any; originalIndex: number }) => (
                <ReflectionItem
                  key={originalIndex}
                  hypothesis={hyp}
                  hypothesisNumber={originalIndex + 1}
                />
              )
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

/**
 * Display a single hypothesis reflection item (within the main card)
 */
function ReflectionItem({
  hypothesis,
  hypothesisNumber,
}: {
  hypothesis: any;
  hypothesisNumber: number;
}) {
  const [showFullAnalysis, setShowFullAnalysis] = useState(false);

  // parse classification from reflection notes
  const classificationMatch = hypothesis.reflection_notes?.match(
    /Classification:\s*(.+?)(?:\n|$)/i
  );
  const classification = classificationMatch ? classificationMatch[1].trim() : "neutral";

  // get reasoning (everything before "Classification:")
  const reasoning = hypothesis.reflection_notes?.split(/Classification:/i)[0]?.trim() || "";

  return (
    <div className="border rounded-lg p-3">
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm">Reflection {hypothesisNumber}</span>
            <Badge variant={getBadgeVariant(classification) as any} className="text-xs">
              {classification}
            </Badge>
          </div>
        </div>

        {/* hypothesis text (truncated) */}
        <div>
          <span className="text-muted-foreground">Hypothesis</span>
          <p className="text-sm line-clamp-2 mt-1">{hypothesis.text}</p>
        </div>

        {/* reasoning preview */}
        <div>
          <span className="text-muted-foreground">Analysis</span>
          <div className="text-sm mt-1 line-clamp-3 text-muted-foreground prose prose-sm max-w-none">
            <ReactMarkdown>{reasoning}</ReactMarkdown>
          </div>
        </div>

        {/* domain-specific enrichment fields for this location (e.g. INDRA evidence) */}
        <DomainCustomFields
          hypothesis={hypothesis as Record<string, unknown>}
          location="reflection"
          compact
        />

        {/* details toggle */}
        <button
          onClick={() => setShowFullAnalysis(!showFullAnalysis)}
          className="text-sm text-th-link hover:text-th-link-hover flex items-center gap-1"
        >
          <ChevronDown
            className={cn("w-4 h-4 transition-transform", showFullAnalysis && "rotate-180")}
          />
          {showFullAnalysis ? "Hide" : "Show"} Full Analysis
        </button>

        {/* expanded details */}
        {showFullAnalysis && (
          <div className="space-y-3 pt-2 border-t">
            {/* full hypothesis text — domain fields already shown above the toggle */}
            <div>
              <h5 className="font-medium mb-2">Full Hypothesis Details</h5>
              <HypothesisDetails
                hypothesis={hypothesis}
                showAllFields={true}
                location="reflection"
                showDomainFields={false}
              />
            </div>

            {/* full reasoning */}
            <div>
              <h5 className="font-medium mb-1">Reflection Analysis</h5>
              <div className="reflection-analysis text-sm prose prose-sm max-w-none">
                <ReactMarkdown>{reasoning}</ReactMarkdown>
              </div>
            </div>

            {/* classification */}
            <div>
              <h5 className="font-medium text-sm mb-1">Classification</h5>
              <Badge variant={getBadgeVariant(classification) as any}>{classification}</Badge>
              <p className="text-xs text-muted-foreground mt-2">
                {classification.toLowerCase().includes("missing piece") &&
                  "This hypothesis offers a novel, plausible explanation for observations."}
                {classification.toLowerCase().includes("already explained") &&
                  "Hypothesis is consistent with observations, but causes are already known."}
                {classification.toLowerCase().includes("other explanations") &&
                  "Hypothesis could explain observations, but better explanations exist."}
                {classification.toLowerCase().includes("neutral") &&
                  "Hypothesis neither explains nor is contradicted by observations."}
                {classification.toLowerCase().includes("disproved") &&
                  "Observations contradict this hypothesis."}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
