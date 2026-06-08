import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { MessageSquare, ChevronDown, ChevronUp } from "lucide-react";
import { useTheme } from "@/context/ThemeContext";

export interface DebateTranscriptProps {
  transcript: string;
  debateId?: string | number;
  hypothesisText?: string;
  inDialog?: boolean;
}

interface Turn {
  number: number;
  content: string;
}

/**
 * Color scheme for turns in light mode - soft pastel backgrounds
 */
const LIGHT_TURN_COLORS = [
  { bg: "bg-blue-50", text: "text-black", label: "text-th-fg" },
  { bg: "bg-purple-50", text: "text-black", label: "text-th-secondary-fg" },
  { bg: "bg-emerald-50", text: "text-black", label: "text-th-accent-fg" },
  { bg: "bg-amber-50", text: "text-black", label: "text-th-fg" },
  { bg: "bg-rose-50", text: "text-black", label: "text-th-secondary-fg" },
  { bg: "bg-teal-50", text: "text-black", label: "text-th-accent-fg" },
];

/**
 * Color scheme for turns in dark mode - darker, more muted backgrounds
 */
const DARK_TURN_COLORS = [
  { bg: "bg-blue-900/30", text: "text-th-fg", label: "text-th-fg" },
  { bg: "bg-purple-900/30", text: "text-th-secondary-fg", label: "text-th-secondary-fg" },
  { bg: "bg-emerald-900/30", text: "text-th-accent-fg", label: "text-th-accent-fg" },
  { bg: "bg-amber-900/30", text: "text-th-fg", label: "text-th-fg" },
  { bg: "bg-rose-900/30", text: "text-th-secondary-fg", label: "text-th-secondary-fg" },
  { bg: "bg-teal-900/30", text: "text-th-accent-fg", label: "text-th-accent-fg" },
];

/**
 * Parses a debate transcript into individual turns
 * Format: "Turn {number}:\n{content}"
 */
function parseTranscript(transcript: string): Turn[] {
  if (!transcript) return [];

  // split by "Turn N:" pattern
  const turnPattern = /Turn (\d+):/g;
  const turns: Turn[] = [];

  let match;
  let lastIndex = 0;
  const matches: { index: number; number: number }[] = [];

  // find all turn markers
  while ((match = turnPattern.exec(transcript)) !== null) {
    matches.push({
      index: match.index,
      number: parseInt(match[1], 10),
    });
  }

  // extract content between turn markers
  for (let i = 0; i < matches.length; i++) {
    const currentMatch = matches[i];
    const nextMatch = matches[i + 1];

    // get content from after "Turn N:" to before next "Turn" or end of string
    const startIndex = currentMatch.index + `Turn ${currentMatch.number}:`.length;
    const endIndex = nextMatch ? nextMatch.index : transcript.length;
    const content = transcript.slice(startIndex, endIndex).trim();

    if (content) {
      turns.push({
        number: currentMatch.number,
        content,
      });
    }
  }

  return turns;
}

/**
 * Displays a debate transcript with chat-like bubbles for each turn
 */
export function DebateTranscript({
  transcript,
  debateId,
  hypothesisText,
  inDialog = false
}: DebateTranscriptProps) {
  const { isDark } = useTheme();
  const turns = parseTranscript(transcript);
  const [collapsedTurns, setCollapsedTurns] = useState<Set<number>>(new Set());
  const turnColors = isDark ? DARK_TURN_COLORS : LIGHT_TURN_COLORS;

  const toggleTurn = (turnNumber: number) => {
    const newCollapsed = new Set(collapsedTurns);
    if (newCollapsed.has(turnNumber)) {
      newCollapsed.delete(turnNumber);
    } else {
      newCollapsed.add(turnNumber);
    }
    setCollapsedTurns(newCollapsed);
  };

  if (turns.length === 0) {
    return (
      <div className="text-muted-foreground text-sm italic">
        No debate turns found
      </div>
    );
  }

  return (
    <div className={inDialog ? "" : "border border-th-border rounded-lg p-4"}>
      {(debateId !== undefined || hypothesisText) && !inDialog && (
        <div className="mb-4 pb-4 border-b border-th-border">
          <div className="flex items-start gap-3">
            <div className="mt-1">
              <MessageSquare className="w-5 h-5" style={{ color: "var(--color-th-fg)" }} />
            </div>
            <div className="flex-1">
              {debateId !== undefined && (
                <h4 className="text-sm font-semibold mb-2 text-th-fg">
                  Debate {debateId}
                </h4>
              )}
              {hypothesisText && (
                <div className="bg-th-card rounded-md p-3 border border-th-border shadow-sm text-th-card-fg">
                  <p className="text-xs font-medium mb-1 text-th-fg">
                    Resulting Hypothesis:
                  </p>
                  <p className="text-sm leading-relaxed">
                    {hypothesisText}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Simplified header for dialog */}
      {hypothesisText && inDialog && (
        <div className="mb-4 pb-4 border-b border-th-border">
          <p className="text-xs font-medium mb-2 text-th-fg">
            Resulting Hypothesis:
          </p>
          <p className="text-sm text-th-fg leading-relaxed">
            {hypothesisText}
          </p>
        </div>
      )}

      {/* Chat bubbles */}
      <div className="space-y-4">
        {turns.map((turn, index) => {
          // alternate alignment: even indices go left, odd go right
          const isLeft = index % 2 === 0;
          const isCollapsed = collapsedTurns.has(index);
          // cycle through 6 colors
          const colorScheme = turnColors[index % turnColors.length];

          return (
            <div
              key={index}
              className={`flex ${isLeft ? "justify-start" : "justify-end"}`}
            >
              <div
                className={`w-[85%] max-w-[85%] rounded-lg border border-th-border ${colorScheme.bg} ${
                  isLeft ? "mr-auto" : "ml-auto"
                }`}
              >
                {/* Turn header - always visible */}
                <button
                  onClick={() => toggleTurn(index)}
                  className={`w-full flex items-center justify-between gap-2 p-3 hover:opacity-80 transition-opacity ${
                    isCollapsed ? "rounded-lg" : "rounded-t-lg"
                  }`}
                >
                  <span className={`text-xs font-semibold ${colorScheme.label}`}>
                    Turn {index + 1}
                  </span>
                  {isCollapsed ? (
                    <ChevronDown className="w-4 h-4 text-th-muted-fg" />
                  ) : (
                    <ChevronUp className="w-4 h-4 text-th-muted-fg" />
                  )}
                </button>

                {/* Turn content - collapsible */}
                {!isCollapsed && (
                  <div className="px-4 pb-4">
                    <div className={`debate-bubble prose prose-sm max-w-none ${colorScheme.text}`}>
                      <ReactMarkdown>{turn.content}</ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
