import React, { useState } from "react";
import { Copy, Download, Trophy } from "lucide-react";
import { Card, CardHeader, CardContent, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/accordion";
import { Progress } from "@/components/ui/progress";
import type { Hypothesis } from "@/types/hypothesis";
import { copyToClipboard, exportToJSON } from "@/utils/exportUtils";
import { useDomainText } from "@/hooks/useDomainText";
import { CitedText } from "@/components/hypothesis/CitedText";
import { CitationList } from "@/components/hypothesis/CitationList";
import { DomainCustomFields } from "@/components/hypothesis/DomainCustomFields";

export interface HypothesisCardProps {
  hypothesis: Hypothesis;
  rank: number;
}

/**
 * Helper to parse structured experiment format
 */
function parseExperiment(experiment: string): { section: string; content: string }[] | null {
  const sections = ["Objective", "Models", "Datasets", "Methodology", "Metrics", "Validation"];
  const parsed: { section: string; content: string }[] = [];

  let hasStructure = false;
  for (const section of sections) {
    const regex = new RegExp(
      `${section}:\\s*(.+?)(?=\\n\\n|${sections.filter((s) => s !== section).join("|")}:|$)`,
      "is"
    );
    const match = experiment.match(regex);
    if (match) {
      hasStructure = true;
      parsed.push({ section, content: match[1].trim() });
    }
  }

  return hasStructure ? parsed : null;
}

export function HypothesisCard({ hypothesis, rank }: HypothesisCardProps) {
  const { t, process, record } = useDomainText();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await copyToClipboard(hypothesis.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExport = () => {
    exportToJSON(hypothesis, `hypothesis-${rank}.json`);
  };

  // use theme colors for medal ranks
  const getRankColor = () => {
    if (rank === 1) return "var(--color-th-warning)"; // gold
    if (rank === 2) return "var(--color-th-muted-fg)"; // silver
    if (rank === 3) return "color-mix(in srgb, var(--color-th-warning) 70%, transparent)"; // bronze
    return "var(--color-th-muted-fg)";
  };
  const rankColor = getRankColor();

  const parsedExperiment = hypothesis.experiment ? parseExperiment(hypothesis.experiment) : null;

  return (
    <Card
      className="overflow-hidden"
      style={{ borderLeftWidth: "3px", borderLeftColor: rankColor, borderRadius: "0" }}
    >
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <Badge
              variant="secondary"
              className="text-lg font-bold px-3 py-1"
              style={{ backgroundColor: rankColor, color: "white" }}
            >
              #{rank}
            </Badge>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">⭐ {hypothesis.score.toFixed(2)}</Badge>
              <Badge variant="outline">
                <Trophy className="w-3 h-3 mr-1" />
                {hypothesis.elo_rating}
              </Badge>
              <Badge variant="outline">
                {hypothesis.win_count}W / {hypothesis.loss_count}L
              </Badge>
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="space-y-4">
          <div className="pb-3 border-b border-th-border">
            <h4 className="text-sm font-semibold text-th-fg mb-2">Hypothesis</h4>
            <p className="text-base leading-relaxed">{hypothesis.text}</p>
          </div>

          {hypothesis.explanation && (
            <div className="pb-3 border-b border-th-border">
              <h4 className="text-sm font-semibold text-th-fg mb-2">Explanation</h4>
              <p className="text-sm leading-relaxed text-th-muted-fg">{hypothesis.explanation}</p>
            </div>
          )}

          {hypothesis.literature_grounding && (
            <div className="pb-3 border-b border-th-border">
              <h4 className="text-sm font-semibold text-th-fg mb-2">Literature Grounding</h4>
              <p className="text-sm leading-relaxed text-th-muted-fg">
                <CitedText
                  text={hypothesis.literature_grounding}
                  citationMap={hypothesis.citation_map}
                />
              </p>
            </div>
          )}

          {hypothesis.experiment && (
            <div className="pb-3">
              <h4 className="text-sm font-semibold text-th-fg mb-2">Experiment Design</h4>
              {parsedExperiment ? (
                <div className="space-y-3">
                  {parsedExperiment.map(({ section, content }) => (
                    <div key={section} className="text-sm">
                      <span className="font-semibold text-th-fg">{section}:</span>{" "}
                      <span className="text-th-muted-fg leading-relaxed">{content}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm leading-relaxed text-th-muted-fg whitespace-pre-wrap">
                  {hypothesis.experiment}
                </p>
              )}
            </div>
          )}

          {hypothesis.citation_map && Object.keys(hypothesis.citation_map).length > 0 && (
            <div className="pb-3 border-b border-th-border">
              <CitationList citationMap={hypothesis.citation_map} />
            </div>
          )}

          <DomainCustomFields hypothesis={hypothesis as unknown as Record<string, unknown>} />
        </div>

        {/* Tags */}
        <div className="flex flex-wrap gap-2">
          {hypothesis.evolution_history.length > 0 && (
            <Badge variant="secondary">
              {t("evolved_label", undefined, { n: hypothesis.evolution_history.length })}
            </Badge>
          )}
          {hypothesis.similarity_cluster_id && (
            <Badge variant="secondary">
              {t("cluster_label")} {hypothesis.similarity_cluster_id}
            </Badge>
          )}
        </div>

        {/* Reviews Accordion */}
        {hypothesis.reviews && hypothesis.reviews.length > 0 && (
          <Accordion type="single" collapsible>
            <AccordionItem value="reviews">
              <AccordionTrigger>
                {process.Plural} ({hypothesis.reviews.length})
              </AccordionTrigger>
              <AccordionContent>
                <div className="space-y-4">
                  {hypothesis.reviews.map((review, index) => (
                    <div key={index} className="p-3 bg-th-muted rounded space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-sm">
                          {process.Singular} #{index + 1}
                        </span>
                        {review.overall_score !== undefined && (
                          <Badge variant="secondary">
                            {(review.overall_score * 10).toFixed(0)}%
                          </Badge>
                        )}
                      </div>

                      {review.review_summary && <p className="text-sm">{review.review_summary}</p>}

                      {/* Scores */}
                      {review.scores && (
                        <div className="space-y-2">
                          {Object.entries(review.scores).map(([key, value]) => (
                            <div key={key} className="space-y-1">
                              <div className="flex items-center justify-between text-xs">
                                <span className="capitalize">{key.replace(/_/g, " ")}</span>
                                <span>{value} / 10</span>
                              </div>
                              <Progress value={(Number(value) / 10) * 100} />
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Strengths & Weaknesses */}
                      {(review.strengths || review.weaknesses) && (
                        <div className="grid grid-cols-2 gap-2 text-xs">
                          {review.strengths && (
                            <div>
                              <span className="font-medium text-th-success">Strengths:</span>
                              <p className="text-muted-foreground mt-1">{review.strengths}</p>
                            </div>
                          )}
                          {review.weaknesses && (
                            <div>
                              <span className="font-medium text-th-destructive">Weaknesses:</span>
                              <p className="text-muted-foreground mt-1">{review.weaknesses}</p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>

            {/* Evolution History */}
            {hypothesis.evolution_history.length > 0 && (
              <AccordionItem value="evolution">
                <AccordionTrigger>{t("evolution_history")}</AccordionTrigger>
                <AccordionContent>
                  <ol className="list-decimal list-inside space-y-2 text-sm">
                    {hypothesis.evolution_history
                      .filter((step) => step && step.trim().length > 0)
                      .map((step, index) => (
                        <li key={index} className="text-muted-foreground">
                          {step}
                        </li>
                      ))}
                  </ol>
                </AccordionContent>
              </AccordionItem>
            )}
          </Accordion>
        )}
      </CardContent>

      <CardFooter className="flex gap-2">
        <Button variant="outline" size="sm" onClick={handleCopy}>
          <Copy className="w-4 h-4 mr-1" />
          {copied ? "Copied!" : "Copy"}
        </Button>
        <Button variant="outline" size="sm" onClick={handleExport}>
          <Download className="w-4 h-4 mr-1" />
          Export
        </Button>
      </CardFooter>
    </Card>
  );
}
