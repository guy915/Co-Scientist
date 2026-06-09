/**
 * CitedText - renders literature_grounding with interactive inline citation chips.
 *
 * Citation keys like [C1], [C2] in the text are replaced with styled chips that:
 *   - Show a hover tooltip with source details (title/authors for papers, display text for other sources)
 *   - Link to the paper URL on click (paper citations only)
 *   - Fall back to plain text for unresolved keys
 */

import React, { useState } from "react";
import type { CitationSource } from "@/types/hypothesis";

interface CitedTextProps {
  text: string;
  citationMap?: Record<string, CitationSource>;
  className?: string;
}

type Segment = { type: "text"; content: string } | { type: "key"; key: string };

function parseSegments(text: string): Segment[] {
  return text
    .split(/(\[C\d+\])/g)
    .filter(Boolean)
    .map((part) => {
      const match = part.match(/^\[(C\d+)\]$/);
      return match
        ? { type: "key" as const, key: match[1] }
        : { type: "text" as const, content: part };
    });
}

function TooltipCard({ source }: { source: CitationSource }) {
  if (source.type === "paper") {
    const authors = source.authors ?? [];
    const authorText =
      authors.length === 0
        ? null
        : authors.length <= 2
          ? authors.join(", ")
          : authors.slice(0, 2).join(", ") + " et al.";

    return (
      <div className="absolute bottom-full left-0 mb-2 z-50 w-64 rounded-md border border-th-border bg-th-card shadow-lg p-2.5 text-xs pointer-events-none">
        <p className="font-medium text-th-fg leading-snug mb-1 line-clamp-3">{source.title}</p>
        {(authorText || source.year) && (
          <p className="text-th-muted-fg">
            {authorText}
            {source.year ? ` (${source.year})` : ""}
          </p>
        )}
      </div>
    );
  }

  // knowledge graph source
  const toolLabel =
    source.tool_id?.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) ??
    "Knowledge graph";

  return (
    <div className="absolute bottom-full left-0 mb-2 z-50 w-64 rounded-md border border-th-border bg-th-card shadow-lg p-2.5 text-xs pointer-events-none">
      <p className="font-medium text-th-fg leading-snug">{source.display}</p>
      <p className="text-th-muted-fg mt-1">{toolLabel}</p>
    </div>
  );
}

function CitationChip({ citationKey, source }: { citationKey: string; source: CitationSource }) {
  const [visible, setVisible] = useState(false);
  const isPaper = source.type === "paper";
  const url = isPaper ? source.url : undefined;
  const label = `[${citationKey}]`;

  const chipSpan = (
    <span
      className={[
        "font-mono text-xs rounded border px-0.5 leading-none",
        isPaper
          ? "text-th-link border-th-border bg-th-card"
          : "text-th-muted-fg border-th-border border-dashed bg-th-muted",
      ].join(" ")}
    >
      {label}
    </span>
  );

  return (
    <span
      className="relative inline"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:opacity-75 transition-opacity"
        >
          {chipSpan}
        </a>
      ) : (
        <span className="cursor-help">{chipSpan}</span>
      )}
      {visible && <TooltipCard source={source} />}
    </span>
  );
}

function UnresolvedKey({ citationKey }: { citationKey: string }) {
  return <span className="font-mono text-xs text-th-muted-fg">[{citationKey}]</span>;
}

export function CitedText({ text, citationMap, className }: CitedTextProps) {
  if (!text) return null;

  const segments = parseSegments(text);
  const hasCitations = citationMap && Object.keys(citationMap).length > 0;

  if (!hasCitations) {
    return <span className={className}>{text}</span>;
  }

  return (
    <span className={className}>
      {segments.map((seg, i) => {
        if (seg.type === "text") {
          return <React.Fragment key={i}>{seg.content}</React.Fragment>;
        }
        const source = citationMap[seg.key];
        return source ? (
          <CitationChip key={i} citationKey={seg.key} source={source} />
        ) : (
          <UnresolvedKey key={i} citationKey={seg.key} />
        );
      })}
    </span>
  );
}
