import { BookOpen, ChevronDown, ExternalLink, Info } from "lucide-react";
import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { AgentOutput } from "@/types/agents";
import { getAgentColor } from "@/utils/agentFormatters";

interface Article {
  title: string;
  url?: string;
  authors?: string[];
  year?: number;
  venue?: string;
  citations?: number;
  abstract?: string;
  content?: string;
  source_id?: string;
  source?: string;
  pdf_links?: string[];
  used_in_analysis?: boolean;
}

export interface LiteratureReviewAgentProps {
  output: AgentOutput;
}

/**
 * display component for literature review agent output
 */
export function LiteratureReviewAgent({ output }: LiteratureReviewAgentProps) {
  const [showDetails, setShowDetails] = useState(false);
  const data = output.parsed;

  // filter articles that were actually analyzed
  const articles = (data?.articles || []) as Article[];
  const analyzedArticles = articles.filter((article) => article.used_in_analysis);

  // external enrichment sources (e.g. INDRA mechanistic statements)
  // keys start after analyzed papers, matching what the generation node assigns
  const enrichmentSources = (data?.context_enrichment_sources || []) as Array<{
    display: string;
    tool_id?: string;
  }>;
  const enrichmentOffset = analyzedArticles.length;

  return (
    <Card className="p-4 literature-review-card">
      <div className="flex items-start gap-3">
        <BookOpen
          className="w-5 h-5 shrink-0 mt-0.5"
          style={{ color: getAgentColor("LiteratureReview") }}
        />
        <div className="flex-1 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <h4 className="font-semibold">Literature Review</h4>
            <Badge variant="outline" className="text-xs">
              {new Date(output.timestamp).toLocaleTimeString()}
            </Badge>
          </div>

          {/* summary */}
          {data?.literature_review_queries && data.literature_review_queries.length > 0 && (
            <p className="text-sm text-muted-foreground">
              Generated {data.literature_review_queries.length}{" "}
              {data.literature_review_queries.length === 1 ? " search query" : " search queries"}
              {analyzedArticles.length > 0 &&
                ` and analyzed ${analyzedArticles.length} ${analyzedArticles.length === 1 ? "paper" : "papers"}`}
            </p>
          )}

          {/* details toggle */}
          <button
            onClick={() => setShowDetails(!showDetails)}
            className="text-sm text-th-link hover:text-th-link-hover flex items-center gap-1"
          >
            <ChevronDown
              className={cn("w-4 h-4 transition-transform", showDetails && "rotate-180")}
            />
            {showDetails ? "Hide" : "Show"} Details
          </button>

          {/* expanded details */}
          {showDetails && (
            <div className="space-y-4 pt-2 border-t">
              {/* articles with reasoning */}
              {data?.articles_with_reasoning && (
                <div>
                  <h3 className="font-medium mb-2">Analysis Summary</h3>
                  <div className="prose max-w-none text-sm text-muted-foreground articles-with-reasoning">
                    <ReactMarkdown>{data.articles_with_reasoning}</ReactMarkdown>
                  </div>
                </div>
              )}

              {/* references section */}
              {(analyzedArticles.length > 0 || enrichmentSources.length > 0) && (
                <div className="pt-4 border-t">
                  <div className="flex items-center gap-2 mb-2">
                    <h3 className="font-medium">References</h3>
                    <div className="group relative inline-block">
                      <Info className="w-4 h-4 text-muted-foreground hover:text-foreground cursor-help" />
                      <div className="invisible group-hover:visible absolute left-0 top-6 z-10 w-80 p-3 bg-th-card text-th-card-fg rounded-md shadow-lg border border-th-border text-xs">
                        <p className="font-medium mb-1">Paper Selection Process</p>
                        <p className="mb-2">
                          Papers are ranked and filtered through multiple criteria:
                        </p>

                        <p className="font-medium mt-2 mb-1">Initial Ranking:</p>
                        <ul className="list-disc list-inside space-y-0.5 ml-2">
                          <li>Publication recency (recent papers prioritized)</li>
                          <li>Relevance to search queries</li>
                        </ul>

                        <p className="font-medium mt-2 mb-1">Access & Quality Filters:</p>
                        <ul className="list-disc list-inside space-y-0.5 ml-2">
                          <li>Full-text availability preferred over abstracts</li>
                          <li>
                            Papers behind paywalls, login gates, or CAPTCHA verification are avoided
                            when alternatives exist
                          </li>
                        </ul>

                        <p className="mt-2 text-muted-foreground">
                          This multi-stage process ensures quality, accessible papers with full
                          content are analyzed.
                        </p>
                      </div>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground mb-3">
                    The following {analyzedArticles.length}{" "}
                    {analyzedArticles.length === 1 ? "paper was" : "papers were"} analyzed in this
                    literature review:
                  </p>
                  {analyzedArticles.length > 0 && (
                    <ol className="space-y-3 text-sm">
                      {analyzedArticles.map((article, idx) => (
                        <li key={idx} className="pl-2">
                          <div className="space-y-1">
                            <div className="flex items-baseline gap-1.5">
                              <span className="font-mono text-xs text-th-link border border-th-border rounded px-0.5 flex-shrink-0">
                                [C{idx + 1}]
                              </span>
                              <span className="font-medium">{article.title}</span>
                            </div>

                            {/* authors and year */}
                            {(article.authors?.length || article.year) && (
                              <div className="text-xs text-muted-foreground pl-7">
                                {article.authors && article.authors.length > 0 && (
                                  <>
                                    {article.authors.slice(0, 3).join(", ")}
                                    {article.authors.length > 3 && " et al."}
                                  </>
                                )}
                                {article.year && <> ({article.year})</>}
                              </div>
                            )}

                            {/* venue */}
                            {article.venue && (
                              <div className="text-xs text-muted-foreground italic pl-7">
                                {article.venue}
                              </div>
                            )}

                            {/* links */}
                            <div className="flex flex-wrap gap-2 pt-1 pl-7">
                              {article.url && (
                                <a
                                  href={article.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1 text-xs text-th-link hover:text-th-link-hover hover:underline"
                                >
                                  <ExternalLink className="w-3 h-3" />
                                  View Paper
                                </a>
                              )}
                              {article.pdf_links &&
                                article.pdf_links.length > 0 &&
                                article.pdf_links.map((pdfUrl, pdfIdx) => (
                                  <a
                                    key={pdfIdx}
                                    href={pdfUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 text-xs text-th-link hover:text-th-link-hover hover:underline"
                                  >
                                    <ExternalLink className="w-3 h-3" />
                                    PDF{" "}
                                    {article.pdf_links && article.pdf_links.length > 1
                                      ? pdfIdx + 1
                                      : ""}
                                  </a>
                                ))}
                              {article.source && (
                                <Badge variant="secondary" className="text-xs">
                                  {article.source === "google_scholar"
                                    ? "Google Scholar"
                                    : article.source === "pubmed"
                                      ? "PubMed"
                                      : article.source}
                                </Badge>
                              )}
                            </div>
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}

                  {/* external enrichment sources (knowledge graph, etc.) */}
                  {enrichmentSources.length > 0 && (
                    <div className={analyzedArticles.length > 0 ? "mt-4 pt-3 border-t" : ""}>
                      <p className="text-xs text-muted-foreground mb-2">
                        External sources ({enrichmentSources.length}):
                      </p>
                      <ol className="space-y-2 text-sm">
                        {enrichmentSources.map((src, idx) => {
                          const key = `C${enrichmentOffset + idx + 1}`;
                          const toolLabel = src.tool_id
                            ?.replace(/_/g, " ")
                            .replace(/\b\w/g, (c) => c.toUpperCase());
                          return (
                            <li key={idx} className="pl-2">
                              <div className="flex items-start gap-1.5">
                                <span className="font-mono text-xs text-th-muted-fg border border-dashed border-th-border rounded px-0.5 flex-shrink-0 mt-px">
                                  [{key}]
                                </span>
                                <div className="space-y-1">
                                  <span className="text-xs text-muted-foreground">
                                    {src.display}
                                  </span>
                                  {toolLabel && (
                                    <div>
                                      <Badge variant="secondary" className="text-xs">
                                        {toolLabel}
                                      </Badge>
                                    </div>
                                  )}
                                </div>
                              </div>
                            </li>
                          );
                        })}
                      </ol>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
