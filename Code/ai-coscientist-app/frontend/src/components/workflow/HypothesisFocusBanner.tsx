import { X, Pin } from "lucide-react";
import { useHypothesisFocus } from "@/context/HypothesisFocusContext";

export function HypothesisFocusBanner() {
  const { pinnedText, unpin } = useHypothesisFocus();

  if (!pinnedText) return null;

  const preview = pinnedText.length > 120 ? pinnedText.slice(0, 120) + "…" : pinnedText;

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-50 flex items-center gap-3 px-4 py-2.5 border-t text-sm shadow-lg"
      style={{
        backgroundColor: "var(--color-th-bg)",
        borderColor: "var(--color-th-primary)",
        borderTopWidth: "2px",
      }}
    >
      <Pin className="w-4 h-4 shrink-0" style={{ color: "var(--color-th-primary)" }} />
      <span className="font-medium shrink-0" style={{ color: "var(--color-th-primary)" }}>Focused on:</span>
      <span className="flex-1 truncate text-th-fg">{preview}</span>
      <button
        onClick={unpin}
        className="shrink-0 flex items-center gap-1 px-2 py-1 rounded hover:bg-th-muted transition-colors cursor-pointer"
        style={{ color: "var(--color-th-muted-fg)" }}
        aria-label="Clear focus"
      >
        <X className="w-3.5 h-3.5" />
        <span className="text-xs">Clear</span>
      </button>
    </div>
  );
}
