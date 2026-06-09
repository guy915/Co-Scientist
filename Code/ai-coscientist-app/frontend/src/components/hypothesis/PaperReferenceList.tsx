import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { PaperReference } from "@/types/hypothesis";

interface PaperReferenceListProps {
  papers: PaperReference[];
  heading?: string;
  compact?: boolean;
}

function formatAuthors(authors: string[]): string {
  if (authors.length === 0) return "";
  if (authors.length <= 3) return authors.join(", ");
  return authors.slice(0, 3).join(", ") + " et al.";
}

function formatSource(source: string): string {
  if (source === "google_scholar") return "Google Scholar";
  if (source === "pubmed") return "PubMed";
  return source;
}

function PaperItem({ paper, compact }: { paper: PaperReference; compact?: boolean }) {
  return (
    <li className="pl-2">
      <div className="space-y-1">
        <div className={compact ? "text-xs font-medium" : "font-medium"}>{paper.title}</div>

        {(paper.authors?.length || paper.year) && (
          <div className="text-xs text-muted-foreground">
            {paper.authors && paper.authors.length > 0 && formatAuthors(paper.authors)}
            {paper.year && <> ({paper.year})</>}
          </div>
        )}

        {paper.venue && <div className="text-xs text-muted-foreground italic">{paper.venue}</div>}

        <div className="flex flex-wrap gap-2 pt-1">
          {paper.url && (
            <a
              href={paper.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-th-link hover:text-th-link-hover hover:underline"
            >
              <ExternalLink className="w-3 h-3" />
              View Paper
            </a>
          )}
          {paper.pdf_links?.map((pdfUrl, idx) => (
            <a
              key={idx}
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-th-link hover:text-th-link-hover hover:underline"
            >
              <ExternalLink className="w-3 h-3" />
              PDF{paper.pdf_links && paper.pdf_links.length > 1 ? ` ${idx + 1}` : ""}
            </a>
          ))}
          {paper.source && (
            <Badge variant="secondary" className="text-xs">
              {formatSource(paper.source)}
            </Badge>
          )}
        </div>
      </div>
    </li>
  );
}

export function PaperReferenceList({
  papers,
  heading = "Papers Used",
  compact = false,
}: PaperReferenceListProps) {
  if (!papers || papers.length === 0) return null;

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
        {papers.map((paper, idx) => (
          <PaperItem key={idx} paper={paper} compact={compact} />
        ))}
      </ol>
    </div>
  );
}
