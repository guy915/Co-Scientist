import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Report, SafetyDecision } from "@/api/runs";
import { reportMarkdownUrl } from "@/api/runs";
import { Download, FileText, AlertTriangle, Copy, Check, Printer } from "lucide-react";

export function ReportTab({
  runId,
  report,
  safety,
}: {
  runId: string;
  report: Report | null;
  safety: SafetyDecision[];
}) {
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const finalSafety = safety.find((s) => s.stage === "final");

  useEffect(() => {
    if (!report) return;
    setLoading(true);
    fetch(reportMarkdownUrl(runId))
      .then((res) => (res.ok ? res.text() : null))
      .then((text) => setMarkdown(text))
      .finally(() => setLoading(false));
  }, [report, runId]);

  async function copyMarkdown() {
    if (!markdown) return;
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore — clipboard may be unavailable in non-secure contexts */
    }
  }

  if (!report) {
    return (
      <div
        className="rounded border p-6 text-sm text-center"
        style={{ borderColor: "var(--color-th-border)", color: "var(--color-th-muted-fg)" }}
      >
        The report appears once the workflow finishes.
      </div>
    );
  }

  return (
    <div className="grid lg:grid-cols-4 gap-4">
      <article
        className="lg:col-span-3 rounded border p-6 wb-fade-in"
        style={{
          borderColor: "var(--color-th-border)",
          backgroundColor: "var(--color-th-card)",
        }}
      >
        {loading && (
          <div className="space-y-2" aria-busy="true">
            <div className="wb-skeleton h-6 w-2/3" />
            <div className="wb-skeleton h-4 w-full" />
            <div className="wb-skeleton h-4 w-5/6" />
            <div className="wb-skeleton h-4 w-4/6" />
          </div>
        )}
        {markdown && (
          <div className="wb-markdown">
            <ReactMarkdown>{markdown}</ReactMarkdown>
          </div>
        )}
      </article>
      <aside className="space-y-3 wb-print-hide">
        <a
          href={reportMarkdownUrl(runId)}
          download
          className="inline-flex items-center gap-2 px-3 py-2 rounded text-sm w-full justify-center transition-opacity hover:opacity-90"
          style={{
            backgroundColor: "var(--color-th-primary)",
            color: "var(--color-th-primary-fg)",
          }}
        >
          <Download className="w-4 h-4" aria-hidden="true" /> Download .md
        </a>
        <a
          href={`data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(report.payload, null, 2))}`}
          download={`${runId}.json`}
          className="inline-flex items-center gap-2 px-3 py-2 rounded text-sm w-full justify-center border transition-colors hover:bg-[color:var(--color-th-secondary)]"
          style={{ borderColor: "var(--color-th-border)" }}
        >
          <FileText className="w-4 h-4" aria-hidden="true" /> Download .json
        </a>
        <button
          type="button"
          onClick={copyMarkdown}
          disabled={!markdown}
          className="inline-flex items-center gap-2 px-3 py-2 rounded text-sm w-full justify-center border transition-colors hover:bg-[color:var(--color-th-secondary)] disabled:opacity-50"
          style={{ borderColor: "var(--color-th-border)" }}
        >
          {copied ? (
            <>
              <Check className="w-4 h-4" aria-hidden="true" /> Copied
            </>
          ) : (
            <>
              <Copy className="w-4 h-4" aria-hidden="true" /> Copy markdown
            </>
          )}
        </button>
        <button
          type="button"
          onClick={() => window.print()}
          className="inline-flex items-center gap-2 px-3 py-2 rounded text-sm w-full justify-center border transition-colors hover:bg-[color:var(--color-th-secondary)]"
          style={{ borderColor: "var(--color-th-border)" }}
        >
          <Printer className="w-4 h-4" aria-hidden="true" /> Print
        </button>
        {finalSafety && finalSafety.decision !== "allow" && (
          <div
            className="rounded border p-3 text-xs"
            style={{
              borderColor: "var(--color-th-warning)",
              backgroundColor: "color-mix(in srgb, var(--color-th-warning) 12%, transparent)",
            }}
          >
            <div className="flex items-center gap-1.5 font-medium mb-1">
              <AlertTriangle className="w-3.5 h-3.5" aria-hidden="true" />
              Final-output safety: {finalSafety.decision}
            </div>
            <div style={{ color: "var(--color-th-muted-fg)" }}>{finalSafety.reason}</div>
          </div>
        )}
      </aside>
    </div>
  );
}
