import '@material/web/button/filled-button.js';
import '@material/web/button/outlined-button.js';
import '@material/web/button/text-button.js';
import '@material/web/chips/chip-set.js';
import '@material/web/chips/filter-chip.js';
import '@material/web/icon/icon.js';
import '@material/web/iconbutton/icon-button.js';

import {
  Fragment,
  type CSSProperties,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {Link, useLocation, useNavigate} from 'react-router-dom';
import {
  createRun,
  listDemoRuns,
  listRuns,
  type Run,
  startRun,
} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {
  FOCUS_OPTIONS,
  inferRunSpec,
  type InferredRunSpec,
  reviseRunSpec,
  TIER_OPTIONS,
} from '../run_spec';
import {GoogleLabsIcon} from '../components/google_labs_icon';

interface ChatEntry {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: number;
}

interface TimelineItem {
  id: string;
  at: number;
  order: number;
  node: ReactNode;
}

const SUGGESTIONS = [
  'Find new therapeutic targets for M.tuberculosis by combining...',
  'Generate novel hypotheses for the link between...',
  'Propose new mechanisms to explain why some patients...',
];

const PROMPT_SUGGESTIONS = [
  'Find new therapeutic targets for M.tuberculosis by combining...',
  'Generate novel hypotheses for the link between...',
  'Propose new mechanisms to explain why some patients...',
];

/** The three phases of a session, shown on the home screen. */
const SESSION_STEPS: ReadonlyArray<{
  n: number;
  title: string;
  body: string;
}> = [
  {
    n: 1,
    title: 'Create a Research goal',
    body: 'Tell Co-Scientist what you plan to research, point it to relevant data, and set your evaluation criteria.',
  },
  {
    n: 2,
    title: 'Generate hypotheses',
    body: 'A team of agents will generate ideas on your topic using their available data',
  },
  {
    n: 3,
    title: 'Evaluate and rank',
    body: 'The agents will evaluate the ideas against your criteria and rank them, tournament-style',
  },
];

type ActiveMessageMode = 'qa' | 'steering';
type ChatWorkspaceLocationState = {
  cosciAction?: 'new-chat' | 'focus-composer';
};

function id(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function inferActiveMessageMode(text: string): ActiveMessageMode {
  const trimmed = text.trim();
  if (
    trimmed.endsWith('?') ||
    /^(why|what|how|when|who|which|explain|tell me|can you|could you)\b/i.test(
      trimmed,
    )
  ) {
    return 'qa';
  }
  return 'steering';
}

function formatHomeRunDate(timestamp: number): string {
  return new Intl.DateTimeFormat(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(timestamp * 1000));
}

function formatHomeRunDuration(run: Run): string {
  if (run.completed_at && run.completed_at > run.created_at) {
    const minutes = Math.max(
      1,
      Math.round((run.completed_at - run.created_at) / 60),
    );
    return `${minutes} minute${minutes === 1 ? '' : 's'}`;
  }
  if (['running', 'queued', 'synthesizing'].includes(run.status)) {
    return 'In progress';
  }
  return run.status.charAt(0).toUpperCase() + run.status.slice(1);
}

function formatHomeRunTimeChip(run: Run): string {
  if (run.completed_at && run.completed_at > run.created_at) {
    return `Total time: ${formatHomeRunDuration(run)}`;
  }
  if (['running', 'queued', 'synthesizing'].includes(run.status)) {
    return `Time elapsed: ${formatHomeRunDuration(run)}`;
  }
  return `Status: ${formatHomeRunStatus(run)}`;
}

function formatHomeRunStatus(run: Run): string {
  return run.status.charAt(0).toUpperCase() + run.status.slice(1);
}

/**
 * Renders the chat-first AI Co-Scientist workspace.
 */
export function ChatWorkspace() {
  const location = useLocation();
  const navigate = useNavigate();
  const [input, setInput] = useState('');
  const [draftSpec, setDraftSpec] = useState<InferredRunSpec | null>(null);
  const [draftSpecCreatedAt, setDraftSpecCreatedAt] = useState<number | null>(
    null,
  );
  const [isEditingSpec, setIsEditingSpec] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [history, setHistory] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const loadHistory = useCallback(async () => {
    const [ownedRuns, demoRuns] = await Promise.all([
      listRuns().catch(() => [] as Run[]),
      listDemoRuns().catch(() => [] as Run[]),
    ]);
    const byId = new Map<string, Run>();
    for (const item of [...ownedRuns, ...demoRuns]) {
      byId.set(item.id, item);
    }
    setHistory([...byId.values()].sort((a, b) => b.updated_at - a.updated_at));
  }, []);

  const resetWorkspace = useCallback(() => {
    setInput('');
    setDraftSpec(null);
    setDraftSpecCreatedAt(null);
    setIsEditingSpec(false);
    setIsStarting(false);
    setMessages([]);
    setError(null);
    void loadHistory();
  }, [loadHistory]);

  const focusComposer = useCallback(() => {
    window.requestAnimationFrame(() => {
      const composer = document.querySelector<HTMLTextAreaElement>(
        '.reference-composer textarea',
      );
      composer?.focus();
    });
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    window.addEventListener('cosci-new-chat', resetWorkspace);
    window.addEventListener('cosci-focus-composer', focusComposer);
    return () => {
      window.removeEventListener('cosci-new-chat', resetWorkspace);
      window.removeEventListener('cosci-focus-composer', focusComposer);
    };
  }, [focusComposer, resetWorkspace]);

  useEffect(() => {
    const state = location.state as ChatWorkspaceLocationState | null;
    if (!state?.cosciAction) return;
    if (state.cosciAction === 'new-chat') resetWorkspace();
    if (state.cosciAction === 'focus-composer') focusComposer();
    void navigate(location.pathname, {replace: true, state: null});
  }, [
    focusComposer,
    location.pathname,
    location.state,
    navigate,
    resetWorkspace,
  ]);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    if (draftSpec) {
      scroller.scrollTop = 0;
      return;
    }
    if (typeof scroller.scrollTo === 'function') {
      scroller.scrollTo({
        top: scroller.scrollHeight,
        behavior: 'smooth',
      });
      return;
    }
    scroller.scrollTop = scroller.scrollHeight;
  }, [messages.length, draftSpec, draftSpecCreatedAt]);

  const hasConversation = messages.length > 0 || Boolean(draftSpec);

  useEffect(() => {
    const title = draftSpec ? conciseTitle(draftSpec.goal) : '';
    window.dispatchEvent(
      new CustomEvent('cosci-header-title', {detail: title}),
    );
    return () => {
      window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: ''}));
    };
  }, [draftSpec]);

  function appendAssistant(
    content: string,
    createdAt = Date.now() / 1000,
  ): number {
    setMessages(prev => [
      ...prev,
      {id: id('assistant'), role: 'assistant', content, created_at: createdAt},
    ]);
    return createdAt;
  }

  function appendUser(content: string, createdAt = Date.now() / 1000): number {
    setMessages(prev => [
      ...prev,
      {id: id('user'), role: 'user', content, created_at: createdAt},
    ]);
    return createdAt;
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput('');
    setError(null);

    if (draftSpec) {
      const sentAt = appendUser(text);
      const next = reviseRunSpec(draftSpec, text);
      setDraftSpec(next);
      setDraftSpecCreatedAt(sentAt + 0.001);
      setIsEditingSpec(false);
      appendAssistant(
        'I updated the run setup. Start it when the spec looks right.',
        sentAt + 0.002,
      );
      return;
    }

    const sentAt = appendUser(text);
    setDraftSpec(inferRunSpec(text));
    setDraftSpecCreatedAt(sentAt + 0.001);
  }

  async function handleStartRun() {
    if (!draftSpec) return;
    setIsStarting(true);
    setError(null);
    try {
      const created = await createRun({
        research_goal: draftSpec.goal,
        requirements: draftSpec.requirements,
        attributes: draftSpec.attributes,
        criteria: draftSpec.criteria,
        focus: draftSpec.focus,
        tier: draftSpec.tier,
        notes: [
          `Requirements: ${draftSpec.requirements.join(' | ')}`,
          `Attributes: ${draftSpec.attributes.join(' | ')}`,
          `Criteria: ${draftSpec.criteria.join(' | ')}`,
          `Focus: ${draftSpec.focus}`,
          `Tier: ${draftSpec.tier}`,
        ].join('\n'),
      });
      setDraftSpec(null);
      setDraftSpecCreatedAt(null);
      setIsEditingSpec(false);
      await startRun(created.id);
      await loadHistory();
      void navigate(`/runs/${created.id}/details`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsStarting(false);
    }
  }

  const timelineItems: TimelineItem[] = [];
  for (const [index, message] of messages.entries()) {
    timelineItems.push({
      id: `local-message-${message.id}`,
      at: message.created_at,
      order: index,
      node: <ChatBubble message={message} />,
    });
  }
  if (draftSpec && draftSpecCreatedAt !== null) {
    timelineItems.push({
      id: 'draft-spec',
      at: draftSpecCreatedAt,
      order: 50,
      node: (
        <RunSpecCard
          spec={draftSpec}
          isEditing={isEditingSpec}
          isStarting={isStarting}
          onEdit={() => {
            setIsEditingSpec(true);
            setInput('Make this run ');
          }}
          onFocusChange={focus =>
            setDraftSpec(current => (current ? {...current, focus} : current))
          }
          onTierChange={tier =>
            setDraftSpec(current => (current ? {...current, tier} : current))
          }
          onStart={() => void handleStartRun()}
        />
      ),
    });
  }
  timelineItems.sort((a, b) => a.at - b.at || a.order - b.order);
  const homeRecentRuns = history.slice(0, 3);
  const hasHomePrompt = Boolean(input.trim());

  return (
    <div className="cosci-workspace">
      <main className="cosci-workspace-main">
        {!hasConversation ? (
          <section className="reference-home-stage">
            <div
              className={
                hasHomePrompt
                  ? 'reference-home-main prompt-open'
                  : 'reference-home-main'
              }
            >
              <div className="google-product-chip reference-chip">
                <GoogleLabsIcon aria-hidden="true" />
                <span>AI Co-Scientist</span>
              </div>
              <h1>Drive novel scientific discovery with Co-Scientist.</h1>

              <ol className="reference-step-timeline">
                {SESSION_STEPS.map(step => (
                  <li key={step.n}>
                    <span>{step.n}</span>
                    <div>
                      <h2>{step.title}</h2>
                      <p>{step.body}</p>
                    </div>
                  </li>
                ))}
              </ol>

              {hasHomePrompt && (
                <p className="reference-prompt-echo">{input.trim()}</p>
              )}

              <div
                className={
                  hasHomePrompt
                    ? 'reference-suggestion-row prompt-open'
                    : 'reference-suggestion-row'
                }
              >
                {(hasHomePrompt
                  ? PROMPT_SUGGESTIONS
                  : SUGGESTIONS.slice(0, 3)
                ).map((suggestion, index) => (
                  <button
                    key={suggestion}
                    type="button"
                    className={input.trim() && index === 0 ? 'selected' : ''}
                    onClick={() => setInput(suggestion)}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>

              <Composer
                input={input}
                setInput={setInput}
                isEditingSpec={false}
                disabled={false}
                large
                reference
                onSubmit={handleSubmit}
                onSuggestion={suggestion => setInput(suggestion)}
              />
            </div>

            <aside className="reference-recents" aria-label="Recent runs">
              <div className="google-recents-heading">
                <md-icon
                  aria-hidden="true"
                  style={{'--md-icon-size': '20px'} as CSSProperties}
                >
                  history
                </md-icon>
                <h2>Recents</h2>
              </div>
              <ol>
                {homeRecentRuns.length ? (
                  homeRecentRuns.map(run => (
                    <li key={run.id}>
                      <Link
                        to={`/runs/${run.id}/details`}
                        className="reference-recent-card"
                        title={run.research_goal}
                      >
                        <span className="reference-recent-meta">
                          <span>{formatHomeRunDate(run.updated_at)}</span>
                          <span>{formatHomeRunTimeChip(run)}</span>
                        </span>
                        <strong>{conciseTitle(run.research_goal)}</strong>
                        <span>{run.research_goal}</span>
                        <span className="reference-recent-chips">
                          <span>
                            <md-icon aria-hidden="true">check_circle</md-icon>
                            {formatHomeRunStatus(run)}
                          </span>
                        </span>
                      </Link>
                    </li>
                  ))
                ) : (
                  <li>
                    <div className="reference-recents-empty">
                      <span className="reference-assistant-dot">
                        <GoogleLabsIcon aria-hidden="true" />
                      </span>
                      <strong>You have not started any sessions yet.</strong>
                    </div>
                  </li>
                )}
              </ol>
            </aside>
          </section>
        ) : (
          <>
            <section ref={scrollRef} className="google-chat-timeline">
              <div className="reference-chat-column">
                {timelineItems.map(item => (
                  <Fragment key={item.id}>{item.node}</Fragment>
                ))}

                {error && (
                  <div
                    role="alert"
                    className="rounded-md border p-3 text-sm"
                    style={{
                      borderColor: 'var(--md-sys-color-error)',
                      color: 'var(--md-sys-color-error)',
                    }}
                  >
                    {error}
                  </div>
                )}
              </div>
            </section>
            <div className="google-chat-composer">
              <div className="reference-chat-column">
                <Composer
                  input={input}
                  setInput={setInput}
                  isEditingSpec={isEditingSpec}
                  activeMessageMode={inferActiveMessageMode(input)}
                  setupDraftMode={Boolean(draftSpec)}
                  disabled={isStarting}
                  reference
                  onSubmit={handleSubmit}
                  onSuggestion={suggestion => setInput(suggestion)}
                />
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function Composer({
  input,
  setInput,
  isEditingSpec,
  activeRunId = null,
  activeMessageMode = 'steering',
  canSteerActiveRun = false,
  isAnswering = false,
  setupDraftMode = false,
  disabled,
  large = false,
  reference = false,
  onSubmit,
  onSuggestion,
}: {
  input: string;
  setInput: (value: string) => void;
  isEditingSpec: boolean;
  activeRunId?: string | null;
  activeMessageMode?: ActiveMessageMode;
  canSteerActiveRun?: boolean;
  isAnswering?: boolean;
  setupDraftMode?: boolean;
  disabled: boolean;
  large?: boolean;
  reference?: boolean;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  onSuggestion: (value: string) => void;
}) {
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  }

  const hasRunContext = Boolean(activeRunId);
  const placeholder = isEditingSpec
    ? 'Describe the change to the run setup...'
    : setupDraftMode
      ? ''
      : hasRunContext
        ? activeMessageMode === 'qa' || !canSteerActiveRun
          ? 'Ask what this run is doing...'
          : 'Ask a question or steer the active run...'
        : '';
  const submitLabel = hasRunContext
    ? isAnswering
      ? 'Answering...'
      : activeMessageMode === 'qa' || !canSteerActiveRun
        ? 'Ask'
        : 'Send'
    : 'Send';

  if (reference) {
    return (
      <form onSubmit={onSubmit} className="reference-composer">
        <label>
          <span>
            <md-icon aria-hidden="true">shield</md-icon>
            {hasRunContext
              ? isEditingSpec
                ? 'Type to edit session details'
                : 'Ask AI Co-Scientist'
              : setupDraftMode
                ? 'Type to edit session details'
                : 'Ask AI Co-Scientist'}
          </span>
          <textarea
            rows={large ? 4 : 3}
            value={input}
            disabled={disabled}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
          />
        </label>
        <div className="reference-composer-actions">
          <button
            type="submit"
            aria-label={submitLabel}
            disabled={!input.trim() || disabled}
          >
            <md-icon aria-hidden="true">send</md-icon>
          </button>
        </div>
      </form>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-xl border p-3"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface-container-low)',
      }}
    >
      <textarea
        className="block w-full resize-none bg-transparent text-base outline-none placeholder:text-[color:var(--md-sys-color-on-surface-variant)]"
        rows={large ? 5 : 3}
        value={input}
        disabled={disabled}
        onChange={e => setInput(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        style={{
          color: 'var(--md-sys-color-on-surface)',
          minHeight: large ? '9rem' : '5.5rem',
        }}
      />
      <div className="flex flex-col gap-2 pt-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          {large && (
            <div className="hidden md:flex flex-wrap gap-1.5">
              {SUGGESTIONS.map(suggestion => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => onSuggestion(suggestion)}
                  className="cursor-pointer rounded-full border px-2.5 py-1 text-xs"
                  style={{
                    borderColor: 'var(--md-sys-color-outline-variant)',
                    color: 'var(--md-sys-color-on-surface-variant)',
                  }}
                >
                  {suggestion.split(' ').slice(0, 6).join(' ')}
                </button>
              ))}
            </div>
          )}
        </div>
        <md-filled-button
          type="submit"
          disabled={!input.trim() || disabled || undefined}
        >
          <md-icon slot="icon" aria-hidden="true">
            arrow_upward
          </md-icon>
          {submitLabel}
        </md-filled-button>
      </div>
    </form>
  );
}

function ChatBubble({message}: {message: ChatEntry}) {
  const isUser = message.role === 'user';
  return (
    <div
      className={isUser ? 'reference-bubble-row user' : 'reference-bubble-row'}
    >
      <div
        className={isUser ? 'reference-user-bubble' : 'reference-model-bubble'}
      >
        <span>{message.content}</span>
        {isUser && <md-icon aria-hidden="true">expand_more</md-icon>}
      </div>
    </div>
  );
}

function RunSpecCard({
  spec,
  isEditing,
  isStarting,
  onEdit,
  onFocusChange,
  onTierChange,
  onStart,
}: {
  spec: InferredRunSpec;
  isEditing: boolean;
  isStarting: boolean;
  onEdit: () => void;
  onFocusChange: (focus: InferredRunSpec['focus']) => void;
  onTierChange: (tier: InferredRunSpec['tier']) => void;
  onStart: () => void;
}) {
  const tier = TIER_OPTIONS.find(option => option.id === spec.tier);
  const focus = FOCUS_OPTIONS.find(option => option.id === spec.focus);

  return (
    <section
      className="reference-setup-message"
      aria-label="Inferred run setup"
    >
      <div className="reference-assistant-label">
        <span className="reference-assistant-dot">
          <GoogleLabsIcon aria-hidden="true" />
        </span>
        <span>AI Co-Scientist</span>
      </div>
      <p>
        Okay, I've drafted the requirements to propose a novel, testable
        hypothesis for this research session. Let me know if you have any
        suggestions.
      </p>
      <p>
        <strong>
          Please review or edit the details below as needed. Once ready, click
          "Start research" to start generating hypotheses.
        </strong>
      </p>
      <div className="reference-setup-document">
        <h2>{referenceSetupTitle(spec.goal)}</h2>
        <dl className="google-setup-grid">
          <SpecRow label="Goal">{spec.goal}</SpecRow>
          <SpecList label="Requirements" values={spec.requirements} />
          <SpecList label="Attributes" values={spec.attributes} />
          <SpecList label="Criteria" values={spec.criteria} />
        </dl>
        <div className="reference-quiet-controls">
          <label>
            Focus
            <select
              value={spec.focus}
              disabled={isStarting}
              onChange={event =>
                onFocusChange(
                  event.currentTarget.value as InferredRunSpec['focus'],
                )
              }
            >
              {FOCUS_OPTIONS.map(option => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Tier
            <select
              value={spec.tier}
              disabled={isStarting}
              onChange={event =>
                onTierChange(
                  event.currentTarget.value as InferredRunSpec['tier'],
                )
              }
            >
              {TIER_OPTIONS.map(option => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <span>
            {focus?.label ?? 'Balanced'} · {tier?.label ?? 'Standard'} depth
          </span>
        </div>
        <div className="reference-setup-actions">
          <button type="button" onClick={onEdit} disabled={isStarting}>
            {isEditing ? 'Editing' : 'Edit details'}
          </button>
          <button type="button" onClick={onStart} disabled={isStarting}>
            {isStarting ? 'Starting...' : 'Start research'}
          </button>
        </div>
      </div>
    </section>
  );
}

function referenceSetupTitle(goal: string): string {
  if (/liver fibrosis|MASLD|MASH/i.test(goal)) {
    return 'Reversing MASLD/MASH Fibrosis Hypothesis';
  }
  return conciseTitle(goal);
}

function SpecRow({label, children}: {label: string; children: ReactNode}) {
  return (
    <div className="google-spec-row">
      <dt style={{color: 'var(--md-sys-color-on-surface-variant)'}}>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function SpecList({label, values}: {label: string; values: string[]}) {
  return (
    <SpecRow label={label}>
      <ul className="google-spec-list">
        {values.map(value => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </SpecRow>
  );
}
