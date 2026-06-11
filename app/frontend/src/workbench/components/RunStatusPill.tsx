import type { RunStatus } from "@/api/runs";

const STYLES: Record<RunStatus, { bg: string; fg: string; label: string }> = {
  draft: {
    bg: "var(--md-sys-color-surface-variant)",
    fg: "var(--md-sys-color-on-surface-variant)",
    label: "Draft",
  },
  queued: {
    bg: "var(--md-sys-color-tertiary-container)",
    fg: "var(--md-sys-color-on-tertiary-container)",
    label: "Queued",
  },
  running: {
    bg: "var(--md-sys-color-tertiary-container)",
    fg: "var(--md-sys-color-on-tertiary-container)",
    label: "Running",
  },
  synthesizing: {
    bg: "var(--md-sys-color-tertiary-container)",
    fg: "var(--md-sys-color-on-tertiary-container)",
    label: "Synthesizing",
  },
  completed: {
    bg: "var(--color-th-success-container)",
    fg: "var(--color-th-on-success-container)",
    label: "Completed",
  },
  failed: {
    bg: "var(--md-sys-color-error-container)",
    fg: "var(--md-sys-color-on-error-container)",
    label: "Failed",
  },
  blocked: {
    bg: "var(--md-sys-color-error-container)",
    fg: "var(--md-sys-color-on-error-container)",
    label: "Blocked (safety)",
  },
  cancelled: {
    bg: "var(--md-sys-color-surface-variant)",
    fg: "var(--md-sys-color-on-surface-variant)",
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
