import {
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from 'react';
import type {Run, SourceRef} from '@/api/runs';
import {useMessages} from '@/hooks/use_messages';
import {citationStateStyle} from '@/workbench/lib/citation_styles';

interface Props {
  run: Run | null;
}

type MessageMode = 'auto' | 'steering' | 'qa';

function MilestoneRow({
  content,
  createdAt,
}: {
  content: string;
  createdAt: number;
}) {
  const time = new Date(createdAt * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
  return (
    <div
      className="flex items-start gap-2 py-1"
      style={{color: 'var(--md-sys-color-on-surface-variant)'}}
    >
      <span
        className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
        style={{backgroundColor: 'var(--md-sys-color-tertiary)'}}
        aria-hidden="true"
      />
      <span className="text-xs flex-1">{content}</span>
      <span className="text-xs shrink-0 opacity-60">{time}</span>
    </div>
  );
}

function UserBubble({
  content,
  kind,
  applied,
}: {
  content: string;
  kind: string;
  applied: boolean;
}) {
  const isSteering = kind === 'steering';
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] space-y-1">
        <div
          className="rounded-xl px-3 py-2 text-sm"
          style={{
            backgroundColor: 'var(--md-sys-color-primary-container)',
            color: 'var(--md-sys-color-on-primary-container)',
          }}
        >
          {content}
        </div>
        {isSteering && (
          <div className="text-right">
            <span
              className="rounded-full px-2 py-0.5 text-xs"
              style={{
                backgroundColor: applied
                  ? 'var(--md-sys-color-secondary-container)'
                  : 'var(--md-sys-color-surface-variant)',
                color: applied
                  ? 'var(--md-sys-color-on-secondary-container)'
                  : 'var(--md-sys-color-on-surface-variant)',
              }}
            >
              {applied ? 'Steering · applied' : 'Steering · pending'}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

/** Render answer text, turning `[n]` tokens that match a source into chips. */
function renderWithCitations(content: string, sources: SourceRef[]): ReactNode {
  if (sources.length === 0) return content;
  const byNumber = new Map(sources.map(s => [s.n, s]));
  return content.split(/(\[\d+\])/g).map((part, i) => {
    const match = /^\[(\d+)\]$/.exec(part);
    const ref = match ? byNumber.get(Number(match[1])) : undefined;
    if (!ref) return part;
    return (
      <sup
        key={i}
        className="mx-0.5 rounded px-1 text-[10px] font-medium"
        style={{
          backgroundColor: 'var(--md-sys-color-secondary-container)',
          color: 'var(--md-sys-color-on-secondary-container)',
        }}
        title={ref.title}
      >
        {part}
      </sup>
    );
  });
}

function SourcesFooter({sources}: {sources: SourceRef[]}) {
  return (
    <div className="mt-2 space-y-1">
      <div
        className="text-xs font-medium opacity-70"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
      >
        Sources
      </div>
      {sources.map(s => {
        const style = citationStateStyle(s.state);
        return (
          <div key={s.n} className="flex items-center gap-2 text-xs">
            <span className="shrink-0 opacity-60">[{s.n}]</span>
            <span className="flex-1 truncate" title={s.title}>
              {s.title}
            </span>
            <span
              className="shrink-0 rounded-full px-2 py-0.5"
              style={{backgroundColor: style.bg, color: style.fg}}
            >
              {style.label}
            </span>
            {s.url && (
              <a
                className="shrink-0 underline"
                href={s.url}
                target="_blank"
                rel="noreferrer"
                style={{color: 'var(--md-sys-color-primary)'}}
              >
                Open
              </a>
            )}
          </div>
        );
      })}
    </div>
  );
}

function AnswerBubble({
  content,
  sources,
}: {
  content: string;
  sources?: SourceRef[];
}) {
  const refs = sources ?? [];
  return (
    <div className="pl-4">
      <div
        className="rounded-xl px-3 py-2 text-sm"
        style={{
          backgroundColor: 'var(--md-sys-color-surface-variant)',
          color: 'var(--md-sys-color-on-surface-variant)',
        }}
      >
        {content ? (
          renderWithCitations(content, refs)
        ) : (
          <span className="opacity-40">Thinking…</span>
        )}
        {refs.length > 0 && <SourcesFooter sources={refs} />}
      </div>
    </div>
  );
}

/**
 * Renders the run's message timeline and a steering/Q&A composer.
 *
 * @param props The run whose messages and live state are shown.
 */
export function ChatTab({run}: Props) {
  const isActive = run?.status === 'running' || run?.status === 'queued';
  const {messages, isAnswering, error, sendSteering, sendQuestion} =
    useMessages(run?.id ?? null, isActive);

  const [input, setInput] = useState('');
  const [mode, setMode] = useState<MessageMode>('auto');
  const bottomRef = useRef<HTMLDivElement>(null);

  const prevCountRef = useRef(0);
  useEffect(() => {
    if (messages.length !== prevCountRef.current) {
      prevCountRef.current = messages.length;
      bottomRef.current?.scrollIntoView({behavior: 'smooth'});
    }
  });

  const effectiveMode =
    mode === 'auto'
      ? input.trim().endsWith('?') ||
        /^(why|what|how|when|who|which|explain|tell me|can you)\b/i.test(
          input.trim(),
        )
        ? 'qa'
        : 'steering'
      : mode;

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isAnswering) return;
    setInput('');
    if (effectiveMode === 'qa') {
      await sendQuestion(text);
    } else {
      await sendSteering(text);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void handleSend();
    }
  };

  if (!run) return null;

  return (
    <div className="flex flex-col gap-0" style={{minHeight: '400px'}}>
      <div className="flex-1 space-y-2 overflow-y-auto pb-4">
        {messages.length === 0 && (
          <p
            className="text-sm py-6 text-center"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            {isActive
              ? 'Milestone updates will appear here. Send a message to steer the run or ask a question.'
              : 'No messages for this run.'}
          </p>
        )}
        {messages.map(msg => {
          if (msg.kind === 'milestone') {
            return (
              <MilestoneRow
                key={msg.id}
                content={msg.content}
                createdAt={msg.created_at}
              />
            );
          }
          if (msg.sender === 'user') {
            return (
              <UserBubble
                key={msg.id}
                content={msg.content}
                kind={msg.kind}
                applied={msg.applied}
              />
            );
          }
          if (msg.kind === 'qa') {
            return (
              <AnswerBubble
                key={msg.id}
                content={msg.content}
                sources={msg.meta?.sources}
              />
            );
          }
          return null;
        })}
        <div ref={bottomRef} />
      </div>

      {error && (
        <p
          className="text-xs mb-2"
          style={{color: 'var(--md-sys-color-error)'}}
        >
          {error}
        </p>
      )}

      {isActive && (
        <div
          className="rounded-xl border p-2 space-y-2"
          style={{
            borderColor: 'var(--md-sys-color-outline-variant)',
            backgroundColor: 'var(--md-sys-color-surface-container-low)',
          }}
        >
          <textarea
            className="w-full resize-none bg-transparent text-sm outline-none placeholder:opacity-50"
            style={{color: 'var(--md-sys-color-on-surface)'}}
            placeholder={
              effectiveMode === 'qa'
                ? 'Ask a question… (Ctrl+Enter to send)'
                : 'Steer the run… (Ctrl+Enter to send)'
            }
            rows={2}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isAnswering}
          />
          <div className="flex items-center justify-between">
            <div className="flex gap-1">
              {(['auto', 'steering', 'qa'] as MessageMode[]).map(m => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className="rounded-full px-2 py-0.5 text-xs capitalize"
                  style={{
                    backgroundColor:
                      mode === m
                        ? 'var(--md-sys-color-secondary-container)'
                        : 'transparent',
                    color:
                      mode === m
                        ? 'var(--md-sys-color-on-secondary-container)'
                        : 'var(--md-sys-color-on-surface-variant)',
                    border: '1px solid var(--md-sys-color-outline-variant)',
                  }}
                >
                  {m === 'auto' ? `auto · ${effectiveMode}` : m}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => void handleSend()}
              disabled={!input.trim() || isAnswering}
              className="rounded-full px-3 py-1 text-xs font-medium disabled:opacity-40"
              style={{
                backgroundColor: 'var(--md-sys-color-primary)',
                color: 'var(--md-sys-color-on-primary)',
              }}
            >
              {isAnswering ? 'Answering…' : 'Send'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
