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
  type RunFocus,
  type RunTier,
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

interface StartedSession {
  id: string;
  title: string;
  at: number;
}

const SUGGESTIONS = [
  {
    short: 'Find new therapeutic targets for M.tuberculosis by combining...',
    full: 'Find new therapeutic targets for M.tuberculosis by combining host-pathogen interaction datasets with recent literature.',
  },
  {
    short: 'Generate novel hypotheses for the link between...',
    full: 'Generate novel hypotheses for the link between synaptic pruning and treatment-resistant neuroinflammation.',
  },
  {
    short: 'Propose new mechanisms to explain why some patients...',
    full: 'Propose new mechanisms to explain why some patients fail to respond to checkpoint inhibitor therapy.',
  },
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

function formatDurationLabel(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes >= 90) {
    const hours = Math.max(1, Math.round(minutes / 60));
    return `${hours} hour${hours === 1 ? '' : 's'}`;
  }
  return `${minutes} minute${minutes === 1 ? '' : 's'}`;
}

function formatHomeRunDuration(run: Run): string {
  const endTime = run.completed_at ?? run.updated_at;
  if (endTime && endTime > run.created_at) {
    return formatDurationLabel(endTime - run.created_at);
  }
  if (run.status === 'completed') {
    return formatDurationLabel(60);
  }
  if (['running', 'queued', 'synthesizing'].includes(run.status)) {
    return 'In progress';
  }
  return run.status.charAt(0).toUpperCase() + run.status.slice(1);
}

function formatHomeRunTimeChip(run: Run): string {
  if (run.status === 'completed') {
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

function homeRunScore(run: Run): number {
  if (run.status === 'failed' || run.status === 'blocked') return 1200;
  const goalSeed = run.research_goal
    .split('')
    .reduce((acc, char) => acc + char.charCodeAt(0), 0);
  return 1240 + (goalSeed % 55);
}

function homeRunIdeaTitles(goal: string): string[] {
  const normalized = goal.toLowerCase();
  if (normalized.includes('ferroptosis') || normalized.includes('pancreatic')) {
    return [
      'Mitochondrial feedback rescue hypothesis',
      'Lipid peroxide buffering threshold hypothesis',
      'Iron-trafficking checkpoint hypothesis',
    ];
  }
  if (
    normalized.includes('fibrosis') ||
    normalized.includes('mash') ||
    normalized.includes('masld')
  ) {
    return [
      'Epigenetic stromal reversal hypothesis',
      'Fibrotic memory erasure hypothesis',
      'Macrophage remodeling checkpoint hypothesis',
    ];
  }
  if (
    normalized.includes('m.tuberculosis') ||
    normalized.includes('tuberculosis')
  ) {
    return [
      'Metabolic refuge disruption hypothesis',
      'Biofilm redox-state vulnerability hypothesis',
      'Quorum-linked susceptibility restoration hypothesis',
    ];
  }
  if (normalized.includes('synaptic') || normalized.includes('pruning')) {
    return [
      'Microglial timing-window pruning hypothesis',
      'Complement-gated flexibility hypothesis',
      'Activity-dependent dendritic retention hypothesis',
    ];
  }
  return [
    conciseTitle(goal),
    'Mechanistic differentiation hypothesis',
    'Evidence-guided intervention hypothesis',
  ];
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
  const [startedSession, setStartedSession] = useState<StartedSession | null>(
    null,
  );
  const [isStarting, setIsStarting] = useState(false);
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [history, setHistory] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [hoveredSuggestion, setHoveredSuggestion] = useState<string | null>(
    null,
  );
  const [showAllRecents, setShowAllRecents] = useState(false);
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
    setStartedSession(null);
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
    if (typeof scroller.scrollTo === 'function') {
      scroller.scrollTo({
        top: scroller.scrollHeight,
        behavior: 'smooth',
      });
      return;
    }
    scroller.scrollTop = scroller.scrollHeight;
  }, [messages.length, draftSpec, draftSpecCreatedAt, startedSession]);

  const hasConversation =
    messages.length > 0 || Boolean(draftSpec) || Boolean(startedSession);

  useEffect(() => {
    const title = draftSpec
      ? conciseTitle(draftSpec.goal)
      : startedSession
        ? startedSession.title
        : '';
    window.dispatchEvent(
      new CustomEvent('cosci-header-title', {detail: title}),
    );
    return () => {
      window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: ''}));
    };
  }, [draftSpec, startedSession]);

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
      const session: StartedSession = {
        id: created.id,
        title: referenceSetupTitle(draftSpec.goal),
        at: Date.now() / 1000,
      };
      setDraftSpec(null);
      setDraftSpecCreatedAt(null);
      await startRun(created.id);
      setStartedSession(session);
      await loadHistory();
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
          isStarting={isStarting}
          onFocusChange={focus =>
            setDraftSpec(current => (current ? {...current, focus} : current))
          }
          onTierChange={tier =>
            setDraftSpec(current => (current ? {...current, tier} : current))
          }
          onCancel={() => setDraftSpec(null)}
          onStart={() => void handleStartRun()}
        />
      ),
    });
  }
  if (startedSession) {
    timelineItems.push({
      id: `started-session-${startedSession.id}`,
      at: startedSession.at,
      order: 60,
      node: (
        <StartedSessionCard
          session={startedSession}
          onOpen={() => void navigate(`/runs/${startedSession.id}/details`)}
          onNewTopic={() => {
            resetWorkspace();
            focusComposer();
          }}
        />
      ),
    });
  }
  timelineItems.sort((a, b) => a.at - b.at || a.order - b.order);
  const homeRecentRuns = showAllRecents ? history : history.slice(0, 4);
  const hasMoreRecents = history.length > homeRecentRuns.length;
  const selectedSuggestion = SUGGESTIONS.find(
    suggestion => suggestion.full === input.trim(),
  );

  return (
    <div className="cosci-workspace">
      <main className="cosci-workspace-main">
        {!hasConversation ? (
          <section className="reference-home-stage">
            <div className="reference-home-main">
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

              <div className="reference-suggestion-row">
                {SUGGESTIONS.map(suggestion => {
                  const isSelected =
                    selectedSuggestion?.full === suggestion.full;
                  const isPreviewed = hoveredSuggestion
                    ? hoveredSuggestion === suggestion.full
                    : isSelected;
                  return (
                    <div
                      key={suggestion.short}
                      className="reference-suggestion-slot"
                    >
                      <p
                        className={
                          isPreviewed
                            ? 'reference-suggestion-preview visible'
                            : 'reference-suggestion-preview'
                        }
                        aria-hidden={!isPreviewed}
                      >
                        {suggestion.full}
                      </p>
                      <button
                        type="button"
                        className={isSelected ? 'selected' : ''}
                        onPointerEnter={() =>
                          setHoveredSuggestion(suggestion.full)
                        }
                        onPointerLeave={() => setHoveredSuggestion(null)}
                        onFocus={() => setHoveredSuggestion(suggestion.full)}
                        onBlur={() => setHoveredSuggestion(null)}
                        onClick={() => setInput(suggestion.full)}
                      >
                        <span className="reference-suggestion-text">
                          {suggestion.short}
                        </span>
                      </button>
                    </div>
                  );
                })}
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
                  homeRecentRuns.map(run => {
                    const topIdeas = homeRunIdeaTitles(run.research_goal);
                    return (
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
                              <md-icon aria-hidden="true">emoji_events</md-icon>
                              Winning ideas
                            </span>
                            <span>
                              <md-icon aria-hidden="true">stars</md-icon>
                              Top score: {homeRunScore(run)}
                            </span>
                          </span>
                          <ol className="reference-winner-list">
                            {topIdeas.map((idea, index) => (
                              <li key={idea}>
                                <span>{index + 1}.</span>
                                <span>{idea}</span>
                              </li>
                            ))}
                          </ol>
                        </Link>
                      </li>
                    );
                  })
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
              {hasMoreRecents && (
                <button
                  type="button"
                  className="reference-load-more"
                  onClick={() => setShowAllRecents(true)}
                >
                  Load more
                </button>
              )}
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
                  isEditingSpec={false}
                  activeMessageMode={inferActiveMessageMode(input)}
                  setupDraftMode={Boolean(draftSpec || startedSession)}
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
  const referenceLabel = hasRunContext
    ? isEditingSpec
      ? 'Type to edit session details'
      : 'Ask Co-Scientist'
    : setupDraftMode
      ? 'Type to edit session details'
      : 'Start a new research goal to begin';
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
      <form
        onSubmit={onSubmit}
        className={
          input.trim() ? 'reference-composer has-input' : 'reference-composer'
        }
      >
        <label>
          <span>
            <md-icon aria-hidden="true">shield</md-icon>
            {referenceLabel}
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
                  key={suggestion.short}
                  type="button"
                  onClick={() => onSuggestion(suggestion.full)}
                  className="cursor-pointer rounded-full border px-2.5 py-1 text-xs"
                  style={{
                    borderColor: 'var(--md-sys-color-outline-variant)',
                    color: 'var(--md-sys-color-on-surface-variant)',
                  }}
                >
                  {suggestion.short}
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
  isStarting,
  onFocusChange,
  onTierChange,
  onCancel,
  onStart,
}: {
  spec: InferredRunSpec;
  isStarting: boolean;
  onFocusChange: (focus: RunFocus) => void;
  onTierChange: (tier: RunTier) => void;
  onCancel: () => void;
  onStart: () => void;
}) {
  return (
    <section
      className="reference-setup-message"
      aria-label="Inferred run setup"
    >
      <p>
        Okay, I've drafted the requirements to propose a novel, testable
        hypothesis for this research session. Let me know if you have any
        suggestions.
      </p>
      <p className="reference-review-copy">
        Please review or edit the details below as needed. Once ready, click
        "Start research" to start generating hypotheses.
      </p>
      <div className="reference-plan-heading">
        <h2>Research plan</h2>
        <md-icon aria-hidden="true">edit</md-icon>
      </div>
      <p className="reference-plan-subheading">
        Here's my plan to tackle the topic:
      </p>
      <div className="reference-setup-document">
        <h3>{referenceSetupTitle(spec.goal)}</h3>
        <dl className="google-setup-grid">
          <SpecRow label="Goal">{spec.goal}</SpecRow>
          <SpecList label="Requirements" values={spec.requirements} />
          <SpecList label="Attributes" values={spec.attributes} />
          <SpecList label="Criteria" values={spec.criteria} />
        </dl>
        <RunOptionGroup
          label="Focus"
          name="focus"
          value={spec.focus}
          options={FOCUS_OPTIONS}
          onChange={value => onFocusChange(value as RunFocus)}
        />
        <RunOptionGroup
          label="Tier"
          name="tier"
          value={spec.tier}
          options={TIER_OPTIONS}
          onChange={value => onTierChange(value as RunTier)}
        />
        <div className="reference-setup-actions">
          <button type="button" onClick={onCancel} disabled={isStarting}>
            Cancel
          </button>
          <button type="button" onClick={onStart} disabled={isStarting}>
            {isStarting ? 'Starting...' : 'Start research'}
          </button>
        </div>
      </div>
    </section>
  );
}

function StartedSessionCard({
  session,
  onOpen,
  onNewTopic,
}: {
  session: StartedSession;
  onOpen: () => void;
  onNewTopic: () => void;
}) {
  return (
    <section
      className="reference-started-message"
      aria-label="Started research session"
    >
      <div className="reference-started-label">
        <span aria-hidden="true">
          <GoogleLabsIcon />
        </span>
        <strong>Co-Scientist</strong>
      </div>
      <div className="reference-started-copy">
        <p>
          Your session has been started and your team of AI agents has started
          research!
        </p>
        <p>
          You can view and interact with your session at any time, but note that
          it might take a few minutes for the first ideas to be ready to view.
        </p>
      </div>
      <button
        type="button"
        className="reference-started-session-card"
        onClick={onOpen}
      >
        <span className="reference-started-session-icon" aria-hidden="true">
          <GoogleLabsIcon />
        </span>
        <span>
          <strong>{session.title}</strong>
          <small>Research session</small>
        </span>
        <span className="reference-started-open">Open</span>
      </button>
      <div className="reference-started-next">
        <p>What would you like to do next?</p>
        <button type="button" onClick={onOpen}>
          View session details
        </button>
        <button type="button" onClick={onNewTopic}>
          Start a new research goal session on a new topic
        </button>
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

function RunOptionGroup({
  label,
  name,
  value,
  options,
  onChange,
}: {
  label: string;
  name: string;
  value: string;
  options: ReadonlyArray<{id: string; label: string; description: string}>;
  onChange: (value: string) => void;
}) {
  return (
    <fieldset className="reference-option-group" aria-label={label}>
      <legend>{label}</legend>
      <div>
        {options.map(option => (
          <label
            key={option.id}
            className={
              option.id === value
                ? 'reference-option-card selected'
                : 'reference-option-card'
            }
          >
            <input
              type="radio"
              name={name}
              value={option.id}
              checked={option.id === value}
              onChange={() => onChange(option.id)}
            />
            <span aria-hidden="true" />
            <strong>{option.label}</strong>
            <small>{option.description}</small>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
