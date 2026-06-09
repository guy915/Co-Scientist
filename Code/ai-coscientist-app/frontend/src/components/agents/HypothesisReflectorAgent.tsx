import { ChevronDown, Eye } from "lucide-react";
import React, { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useHypothesisFocus } from "@/context/HypothesisFocusContext";
import { useDomainText } from "@/hooks/useDomainText";
import { cn } from "@/lib/utils";
import type { AgentOutput } from "@/types/agents";
import { getAgentColor } from "@/utils/agentFormatters";

export interface HypothesisReflectorAgentProps {
  output: AgentOutput;
}

/**
 * Display component for Hypothesis Reflector (Peer Reviewer) agent output
 */
export function HypothesisReflectorAgent({ output }: HypothesisReflectorAgentProps) {
  const [showDetails, setShowDetails] = useState(false);
  const data = output.parsed;

  const { pinnedText, isTracked } = useHypothesisFocus();

  // Handle case where this is a multi-review output (all_reviews array)
  if (data?.all_reviews && Array.isArray(data.all_reviews)) {
    const visibleReviews = pinnedText
      ? data.all_reviews.filter((r: any) => !r.hypothesis_text || isTracked(r.hypothesis_text))
      : data.all_reviews;
    // This is a grouped review output - render each review separately
    return (
      <>
        {visibleReviews.map((review: any, index: number) => (
          <SingleReviewCard
            key={index}
            review={review}
            timestamp={output.timestamp}
            iteration={output.iteration}
          />
        ))}
      </>
    );
  }

  // Single review display
  return (
    <SingleReviewCard review={data} timestamp={output.timestamp} iteration={output.iteration} />
  );
}

/**
 * Display a single review
 */
function SingleReviewCard({
  review,
  timestamp,
  iteration,
}: {
  review: any;
  timestamp: number;
  iteration?: number;
}) {
  const { t } = useDomainText();
  const [showDetails, setShowDetails] = useState(false);
  // Scores are 1-10, so convert to percentage by multiplying by 10
  const overallScore = review?.overall_score ? review.overall_score * 10 : 0;

  // Extract hypothesis number if available
  const hypothesisNumber = review?.hypothesis_index;

  // Determine iteration label
  let iterationLabel = "";
  if (iteration !== undefined && iteration > 0) {
    iterationLabel = ` (Iteration ${iteration})`;
  } else if (iteration === 0) {
    iterationLabel = " (Initial)";
  }

  return (
    <Card className="p-4 my-1.5">
      <div className="flex items-start gap-3">
        <Eye
          className="w-5 h-5 shrink-0 mt-0.5"
          style={{ color: getAgentColor("HypothesisReflector") }}
        />
        <div className="flex-1 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <h4 className="font-semibold">
                Peer Reviewer
                {hypothesisNumber !== undefined && ` ${hypothesisNumber + 1}`}
              </h4>
              <Badge variant={overallScore >= 70 ? "success" : "secondary"} className="text-xs">
                {overallScore.toFixed(0)}%
              </Badge>
            </div>
            <Badge variant="outline" className="text-xs">
              {new Date(timestamp).toLocaleTimeString()}
            </Badge>
          </div>

          {/* Hypothesis Text (Truncated) */}
          {review?.hypothesis_text && (
            <div>
              <span className="text-sm font-semibold">{t("hypothesis_label")}</span>
              <p className="text-sm text-muted-foreground line-clamp-2 mt-1">
                {review.hypothesis_text}
              </p>
            </div>
          )}

          {/* Review Summary */}
          {review?.review_summary && (
            <div>
              <span className="text-sm font-semibold">Summary</span>
              <p className="text-sm mt-1">{review.review_summary}</p>
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
          {showDetails && review && (
            <div className="space-y-3 pt-2 border-t">
              {/* Detailed Scores */}
              {review.scores && (
                <div className="space-y-2">
                  {Object.entries(review.scores).map(([key, value]) => (
                    <div key={key} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="capitalize">{key.replace(/_/g, " ")}</span>
                        <span className="font-medium">{value} / 10</span>
                      </div>
                      <Progress value={(Number(value) / 10) * 100} />
                    </div>
                  ))}
                </div>
              )}

              {/* Constructive Feedback */}
              {review.constructive_feedback && (
                <div>
                  <h5 className="font-medium text-sm mb-1">Constructive Feedback</h5>
                  <p className="text-sm text-muted-foreground">{review.constructive_feedback}</p>
                </div>
              )}

              {/* Strengths & Weaknesses */}
              <div className="grid grid-cols-2 gap-3">
                {review.detailed_feedback?.strengths && (
                  <div>
                    <h5 className="font-medium text-sm mb-1 text-th-success">Strengths</h5>
                    <p className="text-xs text-muted-foreground">
                      {review.detailed_feedback.strengths}
                    </p>
                  </div>
                )}
                {review.detailed_feedback?.weaknesses && (
                  <div>
                    <h5 className="font-medium text-sm mb-1 text-th-destructive">Weaknesses</h5>
                    <p className="text-xs text-muted-foreground">
                      {review.detailed_feedback.weaknesses}
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
