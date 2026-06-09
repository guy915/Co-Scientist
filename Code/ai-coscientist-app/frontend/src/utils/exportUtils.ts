import type { DomainConfig } from "@/domains/types";
import type { Hypothesis } from "@/types/hypothesis";
import { getText } from "./domainResolver";

/**
 * Export data to JSON file
 */
export function exportToJSON(data: any, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  downloadBlob(blob, filename);
}

/**
 * Export hypotheses to CSV file
 */
export function exportToCSV(hypotheses: Hypothesis[], filename: string, config?: DomainConfig) {
  const headers = [
    config ? getText("csv_headers.rank", config, "Rank") : "Rank",
    config ? getText("csv_headers.text", config, "Text") : "Text",
    config ? getText("csv_headers.score", config, "Score") : "Score",
    config ? getText("csv_headers.elo", config, "Elo Rating") : "Elo Rating",
    config ? getText("csv_headers.wins", config, "Win Count") : "Win Count",
    config ? getText("csv_headers.losses", config, "Loss Count") : "Loss Count",
  ];
  const rows = hypotheses.map((h, i) => [
    i + 1,
    h.text,
    h.score.toFixed(3),
    h.elo_rating,
    h.win_count,
    h.loss_count,
  ]);

  const csv = [
    headers.join(","),
    ...rows.map((row) => row.map((cell) => `"${cell}"`).join(",")),
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv" });
  downloadBlob(blob, filename);
}

/**
 * Export hypotheses to Markdown file
 */
export function exportToMarkdown(
  hypotheses: Hypothesis[],
  researchGoal: string,
  filename: string,
  config?: DomainConfig
) {
  const title = config
    ? getText("markdown.title", config, "Hypothesis Generation Results")
    : "Hypothesis Generation Results";
  const goalLabel = config
    ? getText("markdown.goal_label", config, "Research Goal")
    : "Research Goal";
  const resultsLabel = config
    ? getText("markdown.results_label", config, "Top Hypotheses")
    : "Top Hypotheses";
  const tournamentLabel = config
    ? getText("markdown.tournament_label", config, "Ranking Tournament Record")
    : "Ranking Tournament Record";

  const lines: string[] = [
    `# ${title}`,
    ``,
    `**${goalLabel}**: ${researchGoal}`,
    ``,
    `## ${resultsLabel}`,
    ``,
  ];

  hypotheses.forEach((h, i) => {
    lines.push(`### ${i + 1}. ${h.text}`);
    lines.push(``);
    lines.push(`- **Score**: ${h.score.toFixed(3)}`);
    lines.push(`- **Elo Rating**: ${h.elo_rating}`);
    lines.push(`- **${tournamentLabel}**: ${h.win_count}W / ${h.loss_count}L`);

    if (h.evolution_history.length > 0) {
      lines.push(`- **Evolution**: Refined ${h.evolution_history.length}x`);
    }

    lines.push(``);
  });

  const markdown = lines.join("\n");
  const blob = new Blob([markdown], { type: "text/markdown" });
  downloadBlob(blob, filename);
}

/**
 * Helper function to download a blob as a file
 */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Copy text to clipboard
 */
export function copyToClipboard(text: string): Promise<void> {
  return navigator.clipboard.writeText(text);
}
