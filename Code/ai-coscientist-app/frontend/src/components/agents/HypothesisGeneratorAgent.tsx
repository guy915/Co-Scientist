import { useState } from "react";
import { Pin } from "lucide-react";
import { Sparkles, ChevronDown, ChevronUp, MessageSquare, BookOpen, FileText } from "lucide-react";
import { getAgentIconColor } from "@/utils/themeColors";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { AgentOutput } from "@/types/agents";
import { useDomainText } from "@/hooks/useDomainText";
import { useHypothesisFocus } from "@/context/HypothesisFocusContext";
import { isTrackedHypothesis } from "@/utils/hypothesisFocus";
import { HypothesisDetails } from "@/components/hypothesis/HypothesisDetails";
import { DebateTranscript } from "@/components/hypothesis/DebateTranscript";

export interface HypothesisGeneratorAgentProps {
  output: AgentOutput;
}

/**
 * Formats a debate ID for display by ensuring it's a number and adding 1
 * (since IDs start at 0 but UI should display 1, 2, 3...)
 */
function formatDebateId(debateId: unknown): string {
  if (debateId === undefined || debateId === null) {
    return "";
  }

  // Parse to number if it's a string, otherwise use as-is
  const numId = typeof debateId === "string" ? parseInt(debateId, 10) : Number(debateId);

  // Check if it's a valid number
  if (isNaN(numId)) {
    return "";
  }

  // Add 1 to convert from 0-based to 1-based display
  return String(numId + 1);
}

/**
 * Checks if a generation method involves debate
 */
function isDebateMethod(method: string): boolean {
  return method === "debate" || method === "debate_with_literature" || method.includes("debate");
}

/**
 * Display component for Hypothesis Generator agent output
 */
export function HypothesisGeneratorAgent({ output }: HypothesisGeneratorAgentProps) {
  const { t, item } = useDomainText();
  const { pinnedText, pin, unpin, isTracked } = useHypothesisFocus();
  const [showAll, setShowAll] = useState(false);
  const [expandedHypotheses, setExpandedHypotheses] = useState<Set<number>>(new Set());
  const [openTranscriptDialog, setOpenTranscriptDialog] = useState<number | null>(null);

  const data = output.parsed;
  const hypotheses = data?.hypotheses || [];
  const debateTranscripts = data?.debate_transcripts || [];
  const filteredHypotheses = pinnedText
    ? hypotheses.filter((hyp: any) => isTracked(hyp.text || "") || isTracked(hyp.hypothesis || "") || isTrackedHypothesis(hyp, pinnedText))
    : hypotheses;
  const displayedHypotheses = pinnedText
    ? filteredHypotheses
    : showAll ? hypotheses : hypotheses.slice(0, 3);

  const toggleHypothesis = (index: number) => {
    const newExpanded = new Set(expandedHypotheses);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpandedHypotheses(newExpanded);
  };

  // find transcript for a hypothesis based on debate_id
  const findTranscript = (hypothesis: any) => {
    if (!hypothesis.debate_id && hypothesis.debate_id !== 0) return null;
    return debateTranscripts.find((t: any) => t.debate_id === hypothesis.debate_id);
  };

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <Sparkles
          className="w-5 h-5 shrink-0 mt-0.5"
          style={{ color: getAgentIconColor("HypothesisGenerator") }}
        />
        <div className="flex-1 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <h4 className="font-semibold">
              {t("generated_count", undefined, { count: hypotheses.length })}
              {pinnedText && (
                <span className="ml-2 text-xs font-normal text-th-muted-fg">(showing 1 of {hypotheses.length})</span>
              )}
            </h4>
            <Badge variant="outline" className="text-xs">
              {new Date(output.timestamp).toLocaleTimeString()}
            </Badge>
          </div>

          {/* Hypothesis List */}
          <div className="space-y-3">
            {displayedHypotheses.map((hyp: any, displayIndex: number) => {
              // get the actual index in the full hypotheses array
              const actualIndex = hypotheses.indexOf(hyp);
              const isExpanded = expandedHypotheses.has(actualIndex);
              const hasDetails = hyp.explanation || hyp.literature_grounding || hyp.experiment
                || (hyp.papers_used && hyp.papers_used.length > 0);
              const transcript = findTranscript(hyp);
              const hasDebateTranscript = transcript && isDebateMethod(hyp.generation_method);

              return (
                <div
                  key={actualIndex}
                  className="border rounded-md p-3"
                  style={{ backgroundColor: "color-mix(in srgb, var(--color-th-muted) 50%, transparent)" }}
                >
                  <div className="flex items-start gap-2">
                    <span className="text-sm font-semibold text-th-muted-fg mt-0.5">#{actualIndex + 1}</span>

                    <div className="flex-1">
                      {/* Hypothesis text */}
                      <p className="text-sm text-th-fg leading-relaxed mb-2">
                        {hyp.text || JSON.stringify(hyp)}
                      </p>

                      {/* Action buttons and badge - inline */}
                      <div className="flex items-center gap-2 flex-wrap">
                        {/* Pin/unpin button */}
                        <button
                          onClick={() =>
                            pinnedText === (hyp.text || hyp.hypothesis || "").trim() ? unpin() : pin(hyp.text || hyp.hypothesis || "", hyp.hypothesis ? [hyp.hypothesis] : [])
                          }
                          className="h-7 flex items-center gap-1 text-xs px-2 rounded hover:bg-th-muted transition-colors cursor-pointer"
                          style={{ color: isTracked(hyp.text || hyp.hypothesis || "") ? "var(--color-th-primary)" : "var(--color-th-muted-fg)" }}
                          title={isTracked(hyp.text || hyp.hypothesis || "") ? `Unpin ${item.singular}` : `Focus on this ${item.singular}`}
                        >
                          <Pin className="w-3 h-3" />
                          {isTracked(hyp.text || hyp.hypothesis || "") ? "Focused" : "Focus"}
                        </button>
                        {/* Generation method badge - inline with buttons */}
                        {hyp.generation_method && (
                          <Badge
                            variant={isDebateMethod(hyp.generation_method) ? "default" : "secondary"}
                            className="w-fit text-xs flex items-center gap-1"
                          >
                            {isDebateMethod(hyp.generation_method) ? (
                              <>
                                <MessageSquare className="w-3 h-3" />
                                <span>Debate</span>
                              </>
                            ) : hyp.generation_method === "literature" ? (
                              <>
                                <BookOpen className="w-3 h-3" />
                                <span>Literature</span>
                              </>
                            ) : hyp.generation_method === "literature_tools" ? (
                              <>
                                <BookOpen className="w-3 h-3" />
                                <span>Literature Tools</span>
                              </>
                            ) : (
                              <>
                                <FileText className="w-3 h-3" />
                                <span>Standard</span>
                              </>
                            )}
                          </Badge>
                        )}

                        {hasDetails && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => toggleHypothesis(actualIndex)}
                            className="h-7 text-xs"
                          >
                            {isExpanded ? (
                              <>
                                <ChevronUp className="w-3 h-3 mr-1" />
                                Hide Details
                              </>
                            ) : (
                              <>
                                <ChevronDown className="w-3 h-3 mr-1" />
                                Show Details
                              </>
                            )}
                          </Button>
                        )}

                        {hasDebateTranscript && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setOpenTranscriptDialog(actualIndex)}
                            className="h-7 text-xs"
                          >
                            <MessageSquare className="w-3 h-3 mr-1" />
                            Show Debate Transcript
                          </Button>
                        )}
                      </div>

                      {/* Expanded details */}
                      {isExpanded && hasDetails && (
                        <div className="mt-3 pt-3 border-t">
                          <HypothesisDetails hypothesis={hyp} showAllFields={true} />
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Show All Button */}
          {hypotheses.length > 3 && (
            <Button variant="outline" size="sm" onClick={() => setShowAll(!showAll)}>
              {showAll ? t("show_less") : t("show_all", undefined, { count: hypotheses.length })}
            </Button>
          )}
        </div>
      </div>

      {/* Debate Transcript Dialog */}
      <Dialog open={openTranscriptDialog !== null} onOpenChange={(open) => !open && setOpenTranscriptDialog(null)}>
        <DialogContent className="max-w-4xl max-h-[80vh] flex flex-col">
          {openTranscriptDialog !== null && (() => {
            const hyp = hypotheses[openTranscriptDialog];
            if (!hyp) {
              return (
                <>
                  <DialogHeader>
                    <DialogTitle>Debate Transcript</DialogTitle>
                  </DialogHeader>
                  <div className="text-sm text-muted-foreground">Hypothesis not found</div>
                </>
              );
            }

            const transcript = findTranscript(hyp);
            if (!transcript) {
              return (
                <>
                  <DialogHeader>
                    <DialogTitle>Debate {formatDebateId(hyp.debate_id)} Transcript</DialogTitle>
                  </DialogHeader>
                  <div className="text-sm text-muted-foreground">No transcript found</div>
                </>
              );
            }

            return (
              <>
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2 text-th-fg">
                    <MessageSquare className="w-5 h-5" style={{ color: "var(--color-th-fg)" }} />
                    Debate {formatDebateId(hyp.debate_id)} Transcript
                  </DialogTitle>
                </DialogHeader>
                <div className="overflow-y-auto flex-1 -mx-6 px-6">
                  <DebateTranscript
                    transcript={transcript.transcript}
                    debateId={formatDebateId(hyp.debate_id)}
                    hypothesisText={hyp.text}
                    inDialog={true}
                  />
                </div>
              </>
            );
          })()}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
