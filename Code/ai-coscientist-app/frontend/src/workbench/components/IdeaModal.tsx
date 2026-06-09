import { useEffect, useMemo } from "react";
import type {
  CitationRow,
  Evidence,
  Hypothesis,
  Review,
} from "@/api/runs";
import { X } from "lucide-react";

export function IdeaModal({
  hypothesis,
  allHypotheses,
  reviews,
  citations,
  evidence,
  onClose,
}: {
  hypothesis: Hypothesis;
  allHypotheses: Hypothesis[];
  reviews: Review[];
  citations: CitationRow[];
  evidence: Evidence[];
  onClose: () => void;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const evidenceById = useMemo(
    () => Object.fromEntries(evidence.map((e) => [e.id, e])),
    [evidence]
  );
  const parent = hypothesis.parent_id
    ? allHypotheses.find((h) => h.id === hypothesis.parent_id) ?? null
    : null;
  const children = allHypotheses.filter((h) => h.parent_id === hypothesis.id);

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-start justify-center p-6 overflow-y-auto"
      style={{ backgroundColor: "rgba(0,0,0,0.45)" }}
      onClick={onClose}
    >
      <div
        className="max-w-3xl w-full rounded-lg border shadow-lg"
        style={{
          backgroundColor: "var(--color-th-card)",
          borderColor: "var(--color-th-border)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="flex items-start justify-between p-4 border-b"
          style={{ borderColor: "var(--color-th-border)" }}
        >
          <div className="space-y-1">
            <h2 className="text-lg font-semibold leading-snug">{hypothesis.title}</h2>
            <div className="flex flex-wrap gap-2 text-xs" style={{ color: "var(--color-th-muted-fg)" }}>
              <span
                className="px-1.5 py-0.5 rounded font-mono"
                style={{ backgroundColor: "var(--color-th-secondary)" }}
              >
                Elo {hypothesis.elo_rating}
              </span>
              <span>
                gen {hypothesis.generation} · {hypothesis.created_by_agent}
              </span>
              {hypothesis.win_count + hypothesis.loss_count > 0 && (
                <span>
                  {hypothesis.win_count}W · {hypothesis.loss_count}L
                </span>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1 rounded hover:bg-[color:var(--color-th-secondary)]"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="p-4 space-y-4 text-sm">
          <section>
            <h3 className="font-medium mb-1">Statement</h3>
            <p>{hypothesis.statement}</p>
          </section>

          {hypothesis.mechanism && (
            <section>
              <h3 className="font-medium mb-1">Mechanism</h3>
              <p>{hypothesis.mechanism}</p>
            </section>
          )}

          {hypothesis.expected_effect && (
            <section>
              <h3 className="font-medium mb-1">Expected effect</h3>
              <p>{hypothesis.expected_effect}</p>
            </section>
          )}

          {hypothesis.experimental_context && (
            <section>
              <h3 className="font-medium mb-1">Experimental design</h3>
              <p>{hypothesis.experimental_context}</p>
            </section>
          )}

          {(parent || children.length > 0) && (
            <section>
              <h3 className="font-medium mb-1">Lineage</h3>
              <ul className="text-xs space-y-1" style={{ color: "var(--color-th-muted-fg)" }}>
                {parent && <li>↑ Parent: {parent.title}</li>}
                {children.map((c) => (
                  <li key={c.id}>↓ Child: {c.title}</li>
                ))}
              </ul>
            </section>
          )}

          {reviews.length > 0 && (
            <section>
              <h3 className="font-medium mb-1">Reviews &amp; critique</h3>
              <ul className="space-y-2">
                {reviews.map((r) => (
                  <li
                    key={r.id}
                    className="rounded border p-2"
                    style={{ borderColor: "var(--color-th-border)" }}
                  >
                    <div
                      className="text-xs uppercase tracking-wide"
                      style={{ color: "var(--color-th-muted-fg)" }}
                    >
                      {r.reviewer_agent}
                    </div>
                    <div className="font-medium">{r.summary}</div>
                    <p className="text-xs mt-0.5" style={{ color: "var(--color-th-muted-fg)" }}>
                      {r.critique}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {citations.length > 0 && (
            <section>
              <h3 className="font-medium mb-1">Citations</h3>
              <ul className="space-y-1.5">
                {citations.map((c) => {
                  const ev = evidenceById[c.evidence_id];
                  return (
                    <li key={c.id} className="text-xs flex items-start gap-2">
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] uppercase shrink-0"
                        style={{
                          backgroundColor:
                            c.state === "verified"
                              ? "var(--color-th-success)"
                              : c.state === "partial"
                                ? "var(--color-th-warning)"
                                : c.state === "unsupported"
                                  ? "var(--color-th-destructive)"
                                  : "var(--color-th-secondary)",
                          color:
                            c.state === "unavailable"
                              ? "var(--color-th-muted-fg)"
                              : "var(--color-th-bg)",
                        }}
                      >
                        {c.state}
                      </span>
                      <span>
                        {ev ? ev.title : c.evidence_id} — {c.claim}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
