/**
 * CitationList - renders the resolved citation_map as a reference list.
 *
 * Shows all cited sources under sequential [C*] keys: papers first,
 * then any external enrichment sources (knowledge-graph statements, CVEs, etc.).
 * Visual distinction between types is via border style, not key name.
 */

import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { CitationSource, PaperCitation, KGCitation } from "@/types/hypothesis";

interface CitationListProps {
  citationMap: Record<string, CitationSource>;
  heading?: string;
  compact?: boolean;
}

function formatAuthors(authors: string[]): string {
  if (authors.length === 0) return "";
  if (authors.length <= 3) return authors.join(", ");
  return authors.slice(0, 3).join(", ") + " et al.";
}

function KeyBadge({ citationKey, dashed }: { citationKey: string; dashed?: boolean }) {
  return (
    <span
      className={[
        "font-mono text-xs rounded border px-0.5 flex-shrink-0 leading-none self-baseline mt-px",
        dashed
          ? "text-th-muted-fg border-th-border border-dashed bg-th-muted"
          : "text-th-link border-th-border bg-th-card",
      ].join(" ")}
    >
      [{citationKey}]
    </span>
  );
}

function PaperCitationItem({
  citationKey,
  source,
  compact,
}: {
  citationKey: string;
  source: PaperCitation;
  compact?: boolean;
}) {
  return (
    <li className="pl-2">
      <div className="space-y-1">
        <div className="flex items-start gap-1.5">
          <KeyBadge citationKey={citationKey} />
          <span className={compact ? "text-xs font-medium" : "text-sm font-medium"}>
            {source.title}
          </span>
        </div>

        {(source.authors?.length || source.year) && (
          <div className="text-xs text-th-muted-fg pl-7">
            {source.authors && source.authors.length > 0 && formatAuthors(source.authors)}
            {source.year && <> ({source.year})</>}
          </div>
        )}

        <div className="flex flex-wrap gap-2 pt-0.5 pl-7">
          {source.url && (
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-th-link hover:text-th-link-hover hover:underline"
            >
              <ExternalLink className="w-3 h-3" />
              View Paper
            </a>
          )}
          {source.pdf_links?.map((pdfUrl, idx) => (
            <a
              key={idx}
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-th-link hover:text-th-link-hover hover:underline"
            >
              <ExternalLink className="w-3 h-3" />
              {source.pdf_links && source.pdf_links.length > 1 ? `PDF ${idx + 1}` : "PDF"}
            </a>
          ))}
        </div>
      </div>
    </li>
  );
}

function KGCitationItem({
  citationKey,
  source,
  compact,
}: {
  citationKey: string;
  source: KGCitation;
  compact?: boolean;
}) {
  const toolLabel =
    source.tool_id
      ?.replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase()) ?? "Knowledge Graph";

  return (
    <li className="pl-2">
      <div className="space-y-1">
        <div className="flex items-start gap-1.5">
          <KeyBadge citationKey={citationKey} dashed />
          <span className={compact ? "text-xs text-th-muted-fg" : "text-sm text-th-muted-fg"}>
            {source.display}
          </span>
        </div>
        <div className="pl-7">
          <Badge variant="secondary" className="text-xs">
            {toolLabel}
          </Badge>
        </div>
      </div>
    </li>
  );
}

export function CitationList({
  citationMap,
  heading = "Citations",
  compact = false,
}: CitationListProps) {
  if (!citationMap || Object.keys(citationMap).length === 0) return null;

  const entries = Object.entries(citationMap);
  const papers = entries.filter((e): e is [string, PaperCitation] => e[1].type === "paper");
  const kgSources = entries.filter(
    (e): e is [string, KGCitation] => e[1].type === "knowledge_graph"
  );

  return (
    <div>
      <h4
        className={
          compact
            ? "text-sm font-semibold text-th-fg mb-1"
            : "text-sm font-semibold text-th-fg mb-2"
        }
      >
        {heading}
      </h4>
      <ol className="space-y-3 text-sm">
        {papers.map(([key, source]) => (
          <PaperCitationItem key={key} citationKey={key} source={source} compact={compact} />
        ))}
        {kgSources.map(([key, source]) => (
          <KGCitationItem key={key} citationKey={key} source={source} compact={compact} />
        ))}
      </ol>
    </div>
  );
}
