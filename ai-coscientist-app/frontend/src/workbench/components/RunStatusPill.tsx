import type { RunStatus } from "@/api/runs";

const STYLES: Record<RunStatus, { bg: string; fg: string; label: string }> = {
  draft: { bg: "var(--color-th-secondary)", fg: "var(--color-th-secondary-fg)", label: "Draft" },
  queued: { bg: "var(--color-th-info)", fg: "var(--color-th-info-fg)", label: "Queued" },
  running: { bg: "var(--color-th-info)", fg: "var(--color-th-info-fg)", label: "Running" },
  synthesizing: {
    bg: "var(--color-th-info)",
    fg: "var(--color-th-info-fg)",
    label: "Synthesizing",
  },
  completed: {
    bg: "var(--color-th-success)",
    fg: "var(--color-th-success-fg)",
    label: "Completed",
  },
  failed: {
    bg: "var(--color-th-destructive)",
    fg: "var(--color-th-destructive-fg)",
    label: "Failed",
  },
  blocked: {
    bg: "var(--color-th-destructive)",
    fg: "var(--color-th-destructive-fg)",
    label: "Blocked (safety)",
  },
  cancelled: {
    bg: "var(--color-th-secondary)",
    fg: "var(--color-th-secondary-fg)",
    label: "Cancelled",
  },
};

export function RunStatusPill({ status }: { status: RunStatus }) {
  const s = STYLES[status] ?? STYLES.draft;
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ backgroundColor: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  );
}
