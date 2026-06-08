import { Download, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HypothesisCard } from "./HypothesisCard";
import type { Hypothesis } from "@/types/hypothesis";
import { exportToJSON, exportToCSV, exportToMarkdown, copyToClipboard } from "@/utils/exportUtils";
import { useDomainText } from "@/hooks/useDomainText";

export interface HypothesisListProps {
  hypotheses: Hypothesis[];
  researchGoal: string;
  executionTime?: number;
  metrics?: any;
}

export function HypothesisList({
  hypotheses,
  researchGoal,
  executionTime,
  metrics,
}: HypothesisListProps) {
  const { t, item, goal, action, process, record, config } = useDomainText();

  const handleExportAll = () => {
    const data = {
      research_goal: researchGoal,
      hypotheses,
      execution_time: executionTime,
      metrics,
      exported_at: new Date().toISOString(),
    };
    exportToJSON(data, "hypotheses-all.json");
  };

  const handleExportCSV = () => {
    exportToCSV(hypotheses, "hypotheses.csv", config);
  };

  const handleExportMarkdown = () => {
    exportToMarkdown(hypotheses, researchGoal, "hypotheses.md", config);
  };

  const handleCopyAll = async () => {
    const text = hypotheses
      .map((h, i) => `${i + 1}. ${h.text}\n   Score: ${h.score}, Elo: ${h.elo_rating}`)
      .join("\n\n");
    await copyToClipboard(text);
  };

  return (
    <div className="space-y-6">
      {/* Generated Hypotheses Section Header */}
      <div>
        <div className="mb-4">
          <h2 className="text-3xl font-semibold">
            {t("results_title", undefined, { count: hypotheses.length })}
          </h2>
          <p className="mt-1">
            {goal.Singular}: {researchGoal}
          </p>
          <div className="flex flex-wrap gap-2 mt-4">
            <Button variant="outline" size="sm" onClick={handleCopyAll}>
              <Copy className="w-4 h-4 mr-1" />
              Copy All
            </Button>
            <Button variant="outline" size="sm" onClick={handleExportAll}>
              <Download className="w-4 h-4 mr-1" />
              JSON
            </Button>
            <Button variant="outline" size="sm" onClick={handleExportCSV}>
              <Download className="w-4 h-4 mr-1" />
              CSV
            </Button>
            <Button variant="outline" size="sm" onClick={handleExportMarkdown}>
              <Download className="w-4 h-4 mr-1" />
              Markdown
            </Button>
          </div>
        </div>
      </div>

      {/* Hypothesis Cards */}
      <div className="space-y-4">
        {hypotheses.map((hypothesis, index) => (
          <HypothesisCard key={index} hypothesis={hypothesis} rank={index + 1} />
        ))}
      </div>

      {/* Summary Statistics */}
      {(executionTime || metrics) && (
        <div className="pt-6">
          <h3 className="text-xl font-semibold mb-4 text-th-fg">Summary Statistics</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {executionTime !== undefined && executionTime > 0 && (
              <div>
                <p className="text-sm text-muted-foreground">Execution Time</p>
                <p className="text-2xl font-bold text-th-fg">{executionTime.toFixed(1)}s</p>
              </div>
            )}
            {metrics?.hypothesis_count !== undefined && (
              <div>
                <p className="text-sm text-muted-foreground">
                  {item.Plural} {action.Past}
                </p>
                <p className="text-2xl font-bold text-th-fg">{metrics.hypothesis_count}</p>
              </div>
            )}
            {metrics?.reviews_count !== undefined && (
              <div>
                <p className="text-sm text-muted-foreground">{process.Plural}</p>
                <p className="text-2xl font-bold text-th-fg">{metrics.reviews_count}</p>
              </div>
            )}
            {Boolean(metrics?.tournaments_count) && (
              <div>
                <p className="text-sm text-muted-foreground">Tournaments</p>
                <p className="text-2xl font-bold text-th-fg">{metrics.tournaments_count}</p>
              </div>
            )}
            {metrics?.evolutions_count !== undefined && metrics.evolutions_count > 0 && (
              <div>
                <p className="text-sm text-muted-foreground">{record.Plural}</p>
                <p className="text-2xl font-bold text-th-fg">{metrics.evolutions_count}</p>
              </div>
            )}
            {metrics?.llm_calls !== undefined && (
              <div>
                <p className="text-sm text-muted-foreground">LLM Calls</p>
                <p className="text-2xl font-bold text-th-fg">{metrics.llm_calls}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
