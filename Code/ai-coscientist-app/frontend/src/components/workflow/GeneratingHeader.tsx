import React from "react";
import { Loader2, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

export interface GeneratingHeaderProps {
  researchGoal: string;
  progress: number;
  progressMessage: string;
  onCancel: () => void;
  isCancelling?: boolean;
}

/**
 * Header component shown during hypothesis generation
 */
export function GeneratingHeader({
  researchGoal,
  progress,
  progressMessage,
  onCancel,
  isCancelling = false,
}: GeneratingHeaderProps) {
  return (
    <Card className="sticky top-4 z-10 shadow-lg">
      <CardContent className="pt-6">
        <div className="space-y-4">
          {/* Header */}
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 space-y-2">
              <h3 className="font-semibold text-lg">
                {isCancelling ? "Cancelling Generation" : "Generating Hypotheses"}
              </h3>
              <p className="text-sm text-muted-foreground line-clamp-2">{researchGoal}</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={onCancel}
              disabled={isCancelling}
              className="shrink-0 cursor-pointer"
            >
              <X className="w-4 h-4 mr-1" />
              {isCancelling ? "Cancelling..." : "Cancel"}
            </Button>
          </div>

          {/* Progress Bar */}
          <div className="space-y-2">
            <Progress value={progress} className="w-full" />
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="w-4 h-4 animate-spin" />
                {progressMessage}
              </span>
              <span className="font-medium">{Math.round(progress)}%</span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
