import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import type { CitationRow, Hypothesis, Review } from "@/api/runs";

type SortKey = "elo" | "title" | "generation";

export function IdeasTab({
  hypotheses,
  citations,
  reviews,
  onFocus,
}: {
  hypotheses: Hypothesis[];
  citations: CitationRow[];
  reviews: Review[];
  onFocus: (id: string) => void;
}) {
  const [filter, setFilter] = useState<"all" | "initial" | "evolved">("all");
  const [sortKey, setSortKey] = useState<SortKey>("elo");

  const sorted = useMemo(() => {
    const arr = [...hypotheses];
    arr.sort((a, b) => {
      if (sortKey === "elo") return b.elo_rating - a.elo_rating;
      if (sortKey === "title") return a.title.localeCompare(b.title);
      return a.generation - b.generation || b.elo_rating - a.elo_rating;
    });
    return arr;
  }, [hypotheses, sortKey]);

  const filtered = useMemo(
    () =>
      sorted.filter((h) => {
        if (filter === "initial") return !h.parent_id;
        if (filter === "evolved") return !!h.parent_id;
        return true;
      }),
    [sorted, filter]
  );

  if (!hypotheses.length) {
    return <Empty msg="Hypotheses appear here once the generation node runs." />;
  }

  return (
    <div className="space-y-3 wb-fade-in">
      <div className="flex items-center gap-2 text-sm flex-wrap">
        <span style={{ color: "var(--color-th-muted-fg)" }}>Filter:</span>
        {(["all", "initial", "evolved"] as const).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className="px-2 py-0.5 rounded border capitalize transition-colors"
            style={{
              borderColor: filter === f ? "var(--color-th-primary)" : "var(--color-th-border)",
              backgroundColor: filter === f ? "var(--color-th-secondary)" : "transparent",
              fontWeight: filter === f ? 600 : 400,
            }}
          >
            {f}
          </button>
        ))}
        <span className="mx-2" style={{ color: "var(--color-th-muted-fg)" }}>
          ·
        </span>
        <span style={{ color: "var(--color-th-muted-fg)" }}>Sort:</span>
        {(["elo", "title", "generation"] as SortKey[]).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setSortKey(k)}
            className="px-2 py-0.5 rounded border capitalize transition-colors"
            style={{
              borderColor: sortKey === k ? "var(--color-th-primary)" : "var(--color-th-border)",
              backgroundColor: sortKey === k ? "var(--color-th-secondary)" : "transparent",
              fontWeight: sortKey === k ? 600 : 400,
            }}
          >
            {k}
          </button>
        ))}
      </div>
      <ol className="space-y-2">
        {filtered.map((h, i) => (
          <IdeaRow
            key={h.id}
            rank={i + 1}
            h={h}
            citations={citations.filter((c) => c.hypothesis_id === h.id)}
            reviews={reviews.filter((r) => r.hypothesis_id === h.id)}
            onClick={() => onFocus(h.id)}
          />
        ))}
      </ol>
    </div>
  );
}

function IdeaRow({
  rank,
  h,
  citations,
  reviews,
  onClick,
}: {
  rank: number;
  h: Hypothesis;
  citations: CitationRow[];
  reviews: Review[];
  onClick: () => void;
}) {
  const [open, setOpen] = useState(false);
  const verified = citations.filter((c) => c.state === "verified").length;
  const totalCit = citations.length;
  const totalMatches = h.win_count + h.loss_count;
  const winRate = totalMatches ? Math.round((h.win_count / totalMatches) * 100) : null;

  return (
    <li
      className="rounded border transition-colors hover:bg-[color:var(--color-th-secondary)]"
      style={{
        borderColor: "var(--color-th-border)",
        backgroundColor: "var(--color-th-card)",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full text-left p-3 flex items-start gap-3"
      >
        <span
          className="text-xs font-mono mt-0.5 w-7 text-right inline-flex items-center justify-end gap-0.5"
          style={{ color: "var(--color-th-muted-fg)" }}
        >
          {open ? (
            <ChevronDown className="w-3.5 h-3.5 inline" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 inline" />
          )}
          {rank}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium">{h.title}</span>
            <span
              className="text-xs px-1.5 py-0.5 rounded font-mono"
              style={{
                backgroundColor: "var(--color-th-secondary)",
                color: "var(--color-th-secondary-fg)",
              }}
            >
              Elo {h.elo_rating}
            </span>
            {h.parent_id && (
              <span
                className="text-xs px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor: "color-mix(in srgb, var(--color-th-info) 18%, transparent)",
                }}
              >
                gen {h.generation}
              </span>
            )}
            {winRate !== null && (
              <span
                className="text-xs px-1.5 py-0.5 rounded font-mono"
                title={`${h.win_count}W / ${h.loss_count}L`}
                style={{
                  backgroundColor: "color-mix(in srgb, var(--color-th-success) 14%, transparent)",
                }}
              >
                {winRate}%
              </span>
            )}
            {totalCit > 0 && (
              <span className="text-xs" style={{ color: "var(--color-th-muted-fg)" }}>
                {verified}/{totalCit} verified
              </span>
            )}
          </div>
          {!open && (
            <p className="text-xs mt-1 line-clamp-2" style={{ color: "var(--color-th-muted-fg)" }}>
              {h.statement}
            </p>
          )}
        </div>
      </button>
      {open && (
        <div
          className="px-3 pb-3 -mt-1 space-y-2 text-sm wb-fade-in"
          style={{ color: "var(--color-th-fg)" }}
        >
          <p>{h.statement}</p>
          {h.mechanism && (
            <p>
              <strong>Mechanism:</strong> {h.mechanism}
            </p>
          )}
          {h.expected_effect && (
            <p>
              <strong>Expected effect:</strong> {h.expected_effect}
            </p>
          )}
          <div
            className="flex items-center gap-3 text-xs"
            style={{ color: "var(--color-th-muted-fg)" }}
          >
            {reviews.length > 0 && (
              <span>
                {reviews.length} review{reviews.length === 1 ? "" : "s"}
              </span>
            )}
            <button
              type="button"
              className="inline-flex items-center gap-1 underline underline-offset-2"
              onClick={(e) => {
                e.stopPropagation();
                onClick();
              }}
            >
              <ExternalLink className="w-3 h-3" aria-hidden="true" /> Open detail
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div
      className="rounded border p-6 text-sm text-center"
      style={{ borderColor: "var(--color-th-border)", color: "var(--color-th-muted-fg)" }}
    >
      {msg}
    </div>
  );
}
