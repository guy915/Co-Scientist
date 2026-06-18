import '@material/web/button/filled-button.js';
import '@material/web/button/outlined-button.js';
import '@material/web/button/text-button.js';
import '@material/web/chips/chip-set.js';
import '@material/web/chips/filter-chip.js';
import '@material/web/icon/icon.js';
import '@material/web/iconbutton/icon-button.js';

import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {Link} from 'react-router-dom';
import {
  type CitationRow,
  createRun,
  type Evidence,
  getCitations,
  getEvidence,
  getHypotheses,
  getMatches,
  getReport,
  getReviews,
  getRun,
  getSystemStatus,
  type Hypothesis,
  listRuns,
  type MatchRow,
  type Report,
  type Review,
  type Run,
  type RunStatus,
  type RunWithSummary,
  sendMessage as sendRunMessage,
  startRun,
  type SystemStatus,
} from '@/api/runs';
import {type StreamEvent, useRunStream} from '@/hooks/use_run_stream';
import {ThemeToggle} from '../components/theme_toggle';
import {
  inferRunSpec,
  type InferredRunSpec,
  reviseRunSpec,
} from '../run_spec';
import {RunStatusPill} from '../components/run_status_pill';

type PanelKind = 'history' | 'knowledge' | 'settings' | 'why' | null;

interface ChatEntry {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

const SUGGESTIONS = [
  'Identify novel mechanisms of selective autophagy in aging neural tissue.',
  'Propose drug repurposing candidates for triple-negative breast cancer through mitochondrial biogenesis.',
  'Investigate how cold stress reshapes glucose homeostasis via brown adipose signalling.',
  'Discover synthetic lethality partners for KRAS-mutant pancreatic ductal adenocarcinoma.',
];

const TERMINAL_STATUSES: RunStatus[] = [
  'completed',
  'failed',
  'blocked',
  'cancelled',
];

const PROGRESS_STAGES = [
  {
    key: 'supervisor',
    label: 'Supervisor',
    eventTypes: ['supervisor.plan', 'safety.intake'],
  },
  {
    key: 'literature',
    label: 'Literature review',
    eventTypes: ['literature_review'],
  },
  {key: 'generate', label: 'Generate', eventTypes: ['generate']},
  {key: 'ranking', label: 'Tournament', eventTypes: ['ranking']},
  {
    key: 'synthesis',
    label: 'Synthesis',
    eventTypes: ['meta_review', 'citation_audit', 'report'],
  },
] as const;

function id(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isTerminal(status: RunStatus | undefined): boolean {
  return Boolean(status && TERMINAL_STATUSES.includes(status));
}

/**
 * Renders the chat-first Co-Scientist workspace.
 */
export function ChatWorkspace() {
  const [input, setInput] = useState('');
  const [draftSpec, setDraftSpec] = useState<InferredRunSpec | null>(null);
  const [isEditingSpec, setIsEditingSpec] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [run, setRun] = useState<RunWithSummary | Run | null>(null);
  const [history, setHistory] = useState<Run[]>([]);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [citations, setCitations] = useState<CitationRow[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [panelKind, setPanelKind] = useState<PanelKind>(null);
  const [focusedHypothesisId, setFocusedHypothesisId] = useState<string | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const {events, isOpen, terminal} = useRunStream(activeRunId, 0);

  const loadHistory = useCallback(async () => {
    try {
      const runs = await listRuns();
      setHistory(runs);
    } catch {
      // History is helpful but should not block the chat workspace.
    }
  }, []);

  const refreshRun = useCallback(async (runId: string) => {
    const [nextRun, nextHypotheses, nextEvidence, nextMatches, nextReviews,
      nextCitations, nextReport] = await Promise.all([
      getRun(runId),
      getHypotheses(runId),
      getEvidence(runId),
      getMatches(runId),
      getReviews(runId),
      getCitations(runId),
      getReport(runId),
    ]);
    setRun(nextRun);
    setHypotheses(nextHypotheses);
    setEvidence(nextEvidence);
    setMatches(nextMatches);
    setReviews(nextReviews);
    setCitations(nextCitations);
    setReport(nextReport);
  }, []);

  useEffect(() => {
    void loadHistory();
    void getSystemStatus()
      .then(setSystemStatus)
      .catch(() => {});
  }, [loadHistory]);

  useEffect(() => {
    if (!activeRunId) return;
    void refreshRun(activeRunId).catch(e =>
      setError(e instanceof Error ? e.message : String(e)),
    );
  }, [activeRunId, refreshRun]);

  useEffect(() => {
    if (!activeRunId || !events.length) return;
    void refreshRun(activeRunId).catch(() => {});
  }, [activeRunId, events.length, refreshRun]);

  useEffect(() => {
    if (!activeRunId || !terminal) return;
    void refreshRun(activeRunId).catch(() => {});
    void loadHistory();
  }, [activeRunId, loadHistory, refreshRun, terminal]);

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
  }, [messages.length, draftSpec, activeRunId, hypotheses.length, report]);

  const topHypotheses = useMemo(
    () => [...hypotheses].sort((a, b) => b.elo_rating - a.elo_rating).slice(0, 5),
    [hypotheses],
  );

  const focusedHypothesis = useMemo(
    () => hypotheses.find(h => h.id === focusedHypothesisId) ?? null,
    [focusedHypothesisId, hypotheses],
  );

  const hasConversation =
    messages.length > 0 || Boolean(draftSpec) || Boolean(activeRunId);

  const isActiveRun =
    Boolean(activeRunId) &&
    !isTerminal(run?.status) &&
    (isOpen || run?.status === 'queued' || run?.status === 'running');

  function appendAssistant(content: string) {
    setMessages(prev => [...prev, {id: id('assistant'), role: 'assistant', content}]);
  }

  function appendUser(content: string) {
    setMessages(prev => [...prev, {id: id('user'), role: 'user', content}]);
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput('');
    setError(null);
    appendUser(text);

    if (draftSpec) {
      const next = reviseRunSpec(draftSpec, text);
      setDraftSpec(next);
      setIsEditingSpec(false);
      appendAssistant('I updated the run setup. Start it when the spec looks right.');
      return;
    }

    if (!activeRunId) {
      setDraftSpec(inferRunSpec(text));
      return;
    }

    if (isActiveRun && activeRunId) {
      appendAssistant('I will apply that as steering for the active run.');
      try {
        await sendRunMessage(activeRunId, text, 'steering');
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
      return;
    }

    appendAssistant(
      'This run is no longer active. Use the report or the ranked hypothesis cards below to continue reviewing the result.',
    );
  }

  async function handleStartRun() {
    if (!draftSpec) return;
    setIsStarting(true);
    setError(null);
    try {
      const created = await createRun({
        research_goal: draftSpec.goal,
        profile: draftSpec.profile,
        notes: [
          `Mode: ${draftSpec.mode}`,
          `Constraints: ${draftSpec.constraints.join(' | ')}`,
          `Output: ${draftSpec.output}`,
        ].join('\n'),
      });
      setRun(created);
      setActiveRunId(created.id);
      setDraftSpec(null);
      setIsEditingSpec(false);
      appendAssistant('Starting the run. I will keep the progress compact here.');
      await startRun(created.id);
      await refreshRun(created.id);
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsStarting(false);
    }
  }

  function openRun(runId: string) {
    setDraftSpec(null);
    setIsEditingSpec(false);
    setActiveRunId(runId);
    setPanelKind(null);
    appendAssistant('Opened that run in the chat workspace.');
  }

  function openWhyPanel(hypothesisId: string) {
    setFocusedHypothesisId(hypothesisId);
    setPanelKind('why');
  }

  const panel = renderPanel({
    panelKind,
    history,
    activeRunId,
    openRun,
    evidence,
    systemStatus,
    focusedHypothesis,
    reviews,
    citations,
    matches,
    onClose: () => setPanelKind(null),
  });

  return (
    <div
      className={
        panel
          ? 'min-h-screen grid grid-rows-[64px_1fr_auto] sm:grid-rows-1 sm:grid-cols-[76px_minmax(0,1fr)] xl:grid-cols-[76px_minmax(0,1fr)_360px]'
          : 'min-h-screen grid grid-rows-[64px_1fr] sm:grid-rows-1 sm:grid-cols-[76px_minmax(0,1fr)]'
      }
      style={{
        backgroundColor: 'var(--md-sys-color-surface)',
        color: 'var(--md-sys-color-on-surface)',
      }}
    >
      <WorkspaceSidebar
        activePanel={panelKind}
        onOpenPanel={setPanelKind}
      />

      <main className="min-w-0 min-h-0 flex flex-col">
        {!hasConversation ? (
          <section className="flex flex-1 items-center justify-center px-4 py-8 sm:px-8">
            <div className="w-full max-w-3xl space-y-5">
              <div className="text-center space-y-2">
                <h1 className="text-[2rem] sm:text-[2.75rem] font-medium leading-tight tracking-normal">
                  What should we investigate?
                </h1>
              </div>
              <Composer
                input={input}
                setInput={setInput}
                isEditingSpec={false}
                disabled={false}
                large
                onSubmit={handleSubmit}
                onSuggestion={suggestion => setInput(suggestion)}
              />
            </div>
          </section>
        ) : (
          <>
            <section
              ref={scrollRef}
              className="flex-1 overflow-y-auto px-4 py-6 sm:px-8"
            >
              <div className="mx-auto max-w-3xl space-y-4 pb-4">
                {messages.map(message => (
                  <ChatBubble key={message.id} message={message} />
                ))}

                {draftSpec && (
                  <RunSpecCard
                    spec={draftSpec}
                    isEditing={isEditingSpec}
                    isStarting={isStarting}
                    onEdit={() => {
                      setIsEditingSpec(true);
                      setInput('Make this run ');
                    }}
                    onStart={() => void handleStartRun()}
                  />
                )}

                {activeRunId && (
                  <RunStatusCard
                    run={run}
                    events={events}
                    isOpen={isOpen}
                    terminal={terminal}
                  />
                )}

                {activeRunId && (
                  <ProgressCards
                    events={events}
                    runStatus={run?.status}
                    hypothesesCount={hypotheses.length}
                    evidenceCount={evidence.length}
                    matchCount={matches.length}
                    hasReport={Boolean(report)}
                  />
                )}

                {topHypotheses.length > 0 && (
                  <section className="space-y-2" aria-label="Top hypotheses">
                    <AssistantLine>
                      Here are the current leading hypotheses. Open “why this
                      ranked” when you need the evidence trail.
                    </AssistantLine>
                    <ol className="space-y-2">
                      {topHypotheses.map((hypothesis, index) => (
                        <HypothesisChatCard
                          key={hypothesis.id}
                          hypothesis={hypothesis}
                          rank={index + 1}
                          evidenceCount={
                            citations.filter(
                              c => c.hypothesis_id === hypothesis.id,
                            ).length
                          }
                          onWhy={() => openWhyPanel(hypothesis.id)}
                        />
                      ))}
                    </ol>
                  </section>
                )}

                {report && activeRunId && (
                  <ReportReadyCard runId={activeRunId} />
                )}

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
            <div
              className="border-t px-4 py-3 sm:px-8"
              style={{
                borderColor: 'var(--md-sys-color-outline-variant)',
                backgroundColor:
                  'color-mix(in srgb, var(--md-sys-color-surface-container-low) 76%, transparent)',
              }}
            >
              <div className="mx-auto max-w-3xl">
                <Composer
                  input={input}
                  setInput={setInput}
                  isEditingSpec={isEditingSpec}
                  disabled={isStarting}
                  onSubmit={handleSubmit}
                  onSuggestion={suggestion => setInput(suggestion)}
                />
              </div>
            </div>
          </>
        )}
      </main>

      {panel}
    </div>
  );
}

function WorkspaceSidebar({
  activePanel,
  onOpenPanel,
}: {
  activePanel: PanelKind;
  onOpenPanel: (panel: PanelKind) => void;
}) {
  const items: Array<{kind: Exclude<PanelKind, null | 'why'>; icon: string; label: string}> = [
    {kind: 'history', icon: 'history', label: 'History'},
    {kind: 'knowledge', icon: 'library_books', label: 'Knowledge Base'},
    {kind: 'settings', icon: 'settings', label: 'Settings'},
  ];

  return (
    <aside
      className="border-b sm:border-b-0 sm:border-r flex sm:flex-col items-center justify-between gap-1 px-3 py-2 sm:px-2 sm:py-4"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface-container-low)',
      }}
    >
      <Link
        to="/"
        className="hidden sm:flex h-11 w-11 items-center justify-center rounded-full"
        style={{
          backgroundColor: 'var(--md-sys-color-primary-container)',
          color: 'var(--md-sys-color-on-primary-container)',
        }}
        aria-label="Co-Scientist workspace"
      >
        <md-icon aria-hidden="true">science</md-icon>
      </Link>
      <nav className="flex sm:flex-col items-center gap-1 w-full sm:mt-6">
        {items.map(item => {
          const selected = activePanel === item.kind;
          return (
            <button
              key={item.kind}
              type="button"
              onClick={() => onOpenPanel(selected ? null : item.kind)}
              className="cursor-pointer h-12 sm:h-14 min-w-0 flex-1 sm:w-full sm:flex-none rounded-xl flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors"
              style={{
                backgroundColor: selected
                  ? 'var(--md-sys-color-secondary-container)'
                  : 'transparent',
                color: selected
                  ? 'var(--md-sys-color-on-secondary-container)'
                  : 'var(--md-sys-color-on-surface-variant)',
              }}
            >
              <md-icon style={{fontSize: '20px'}} aria-hidden="true">
                {item.icon}
              </md-icon>
              <span className="truncate px-1">{item.label}</span>
            </button>
          );
        })}
      </nav>
      <Link
        to="/runs"
        className="hidden sm:flex h-10 w-10 items-center justify-center rounded-full"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
        aria-label="Structured run dashboard"
        title="Structured run dashboard"
      >
        <md-icon aria-hidden="true">table_chart</md-icon>
      </Link>
    </aside>
  );
}

function Composer({
  input,
  setInput,
  isEditingSpec,
  disabled,
  large = false,
  onSubmit,
  onSuggestion,
}: {
  input: string;
  setInput: (value: string) => void;
  isEditingSpec: boolean;
  disabled: boolean;
  large?: boolean;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  onSuggestion: (value: string) => void;
}) {
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
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
        placeholder={
          isEditingSpec
            ? 'Describe the change to the run setup...'
            : 'Describe a research goal...'
        }
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
          Send
        </md-filled-button>
      </div>
    </form>
  );
}

function ChatBubble({message}: {message: ChatEntry}) {
  const isUser = message.role === 'user';
  return (
    <div className={isUser ? 'flex justify-end' : 'flex justify-start'}>
      <div
        className="max-w-[88%] rounded-xl px-3 py-2 text-sm leading-relaxed"
        style={{
          backgroundColor: isUser
            ? 'var(--md-sys-color-primary-container)'
            : 'var(--md-sys-color-surface-container-low)',
          color: isUser
            ? 'var(--md-sys-color-on-primary-container)'
            : 'var(--md-sys-color-on-surface)',
          border: isUser
            ? '1px solid transparent'
            : '1px solid var(--md-sys-color-outline-variant)',
        }}
      >
        {message.content}
      </div>
    </div>
  );
}

function AssistantLine({children}: {children: ReactNode}) {
  return (
    <p
      className="text-sm leading-relaxed"
      style={{color: 'var(--md-sys-color-on-surface-variant)'}}
    >
      {children}
    </p>
  );
}

function RunSpecCard({
  spec,
  isEditing,
  isStarting,
  onEdit,
  onStart,
}: {
  spec: InferredRunSpec;
  isEditing: boolean;
  isStarting: boolean;
  onEdit: () => void;
  onStart: () => void;
}) {
  return (
    <section
      className="rounded-xl border p-3 wb-fade-in"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface-container-low)',
      }}
    >
      <details open>
        <summary className="cursor-pointer text-sm font-semibold">
          Inferred run setup
        </summary>
        <dl className="mt-3 grid gap-2 text-sm">
          <SpecRow label="Goal">{spec.goal}</SpecRow>
          <SpecRow label="Mode">{spec.mode}</SpecRow>
          <SpecRow label="Constraints">{spec.constraints.join(' ')}</SpecRow>
          <SpecRow label="Output">{spec.output}</SpecRow>
        </dl>
      </details>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm font-medium">Start this run?</p>
        <div className="flex items-center gap-2">
          <md-outlined-button
            onclick={onEdit as unknown as EventListener}
            disabled={isStarting || undefined}
          >
            <md-icon slot="icon" aria-hidden="true">
              edit
            </md-icon>
            {isEditing ? 'Editing' : 'Edit'}
          </md-outlined-button>
          <md-filled-button
            onclick={onStart as unknown as EventListener}
            disabled={isStarting || undefined}
          >
            <md-icon slot="icon" aria-hidden="true">
              play_arrow
            </md-icon>
            {isStarting ? 'Starting...' : 'Start'}
          </md-filled-button>
        </div>
      </div>
    </section>
  );
}

function SpecRow({label, children}: {label: string; children: ReactNode}) {
  return (
    <div className="grid gap-1 sm:grid-cols-[6.5rem_1fr]">
      <dt
        className="text-xs font-semibold uppercase tracking-wide"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
      >
        {label}
      </dt>
      <dd>{children}</dd>
    </div>
  );
}

function RunStatusCard({
  run,
  events,
  isOpen,
  terminal,
}: {
  run: RunWithSummary | Run | null;
  events: StreamEvent[];
  isOpen: boolean;
  terminal: boolean;
}) {
  const lastEvent = events.at(-1);
  return (
    <section
      className="rounded-xl border p-3 text-sm wb-fade-in"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface-container-low)',
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {run && <RunStatusPill status={run.status} />}
          {isOpen && !terminal && (
            <span className="inline-flex items-center gap-1">
              <span className="wb-live-dot" aria-hidden="true" />
              live
            </span>
          )}
        </div>
        {run && (
          <Link
            to={`/runs/${run.id}`}
            className="inline-flex items-center gap-1 text-sm underline underline-offset-2"
            style={{color: 'var(--md-sys-color-primary)'}}
          >
            Structured workspace
            <md-icon style={{fontSize: '14px'}} aria-hidden="true">
              open_in_new
            </md-icon>
          </Link>
        )}
      </div>
      <p className="mt-2 font-medium leading-snug">
        {run?.research_goal ?? 'Preparing the run...'}
      </p>
      {lastEvent && (
        <p
          className="mt-1 text-xs"
          style={{color: 'var(--md-sys-color-on-surface-variant)'}}
        >
          Latest: {formatEventName(lastEvent.type)}
        </p>
      )}
    </section>
  );
}

function ProgressCards({
  events,
  runStatus,
  hypothesesCount,
  evidenceCount,
  matchCount,
  hasReport,
}: {
  events: StreamEvent[];
  runStatus: RunStatus | undefined;
  hypothesesCount: number;
  evidenceCount: number;
  matchCount: number;
  hasReport: boolean;
}) {
  const completedEventTypes = new Set(events.map(event => event.type));
  const firstIncomplete = PROGRESS_STAGES.findIndex(
    stage => !stage.eventTypes.some(type => completedEventTypes.has(type)),
  );

  return (
    <section className="grid gap-2 sm:grid-cols-5" aria-label="Run progress">
      {PROGRESS_STAGES.map((stage, index) => {
        const done = stage.eventTypes.some(type => completedEventTypes.has(type));
        const active =
          !done &&
          !isTerminal(runStatus) &&
          firstIncomplete >= 0 &&
          index === firstIncomplete;
        return (
          <div
            key={stage.key}
            className="rounded-md border p-2"
            style={{
              borderColor: done
                ? 'var(--md-sys-color-primary)'
                : 'var(--md-sys-color-outline-variant)',
              backgroundColor: done
                ? 'color-mix(in srgb, var(--md-sys-color-primary) 10%, transparent)'
                : 'var(--md-sys-color-surface-container-low)',
            }}
          >
            <div className="flex items-center gap-1.5 text-xs font-semibold">
              <span
                className="h-2 w-2 rounded-full"
                style={{
                  backgroundColor: done
                    ? 'var(--md-sys-color-primary)'
                    : active
                      ? 'var(--color-th-warning)'
                      : 'var(--md-sys-color-outline)',
                }}
              />
              {stage.label}
            </div>
            <p
              className="mt-1 text-[11px]"
              style={{color: 'var(--md-sys-color-on-surface-variant)'}}
            >
              {progressMetric(stage.key, {
                hypothesesCount,
                evidenceCount,
                matchCount,
                hasReport,
              })}
            </p>
          </div>
        );
      })}
    </section>
  );
}

function progressMetric(
  key: (typeof PROGRESS_STAGES)[number]['key'],
  counts: {
    hypothesesCount: number;
    evidenceCount: number;
    matchCount: number;
    hasReport: boolean;
  },
): string {
  switch (key) {
    case 'literature':
      return `${counts.evidenceCount} evidence`;
    case 'generate':
      return `${counts.hypothesesCount} hypotheses`;
    case 'ranking':
      return `${counts.matchCount} matches`;
    case 'synthesis':
      return counts.hasReport ? 'Report ready' : 'Pending report';
    default:
      return 'Scoped';
  }
}

function HypothesisChatCard({
  hypothesis,
  rank,
  evidenceCount,
  onWhy,
}: {
  hypothesis: Hypothesis;
  rank: number;
  evidenceCount: number;
  onWhy: () => void;
}) {
  return (
    <li
      className="rounded-xl border p-3 wb-fade-in"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface-container-low)',
      }}
    >
      <div className="flex items-start gap-3">
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold"
          style={{
            backgroundColor: 'var(--md-sys-color-secondary-container)',
            color: 'var(--md-sys-color-on-secondary-container)',
          }}
        >
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="min-w-0 flex-1 text-sm font-semibold leading-snug">
              {hypothesis.title}
            </h3>
            <span
              className="rounded-md px-1.5 py-0.5 font-mono text-xs"
              style={{
                backgroundColor: 'var(--md-sys-color-secondary-container)',
              }}
            >
              Elo {hypothesis.elo_rating}
            </span>
          </div>
          <p
            className="mt-1 line-clamp-2 text-xs leading-relaxed"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            {hypothesis.mechanism ?? hypothesis.statement}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
            <span>{evidenceCount} evidence links</span>
            <span>
              {hypothesis.win_count}W / {hypothesis.loss_count}L
            </span>
            <md-text-button onclick={onWhy as unknown as EventListener}>
              why this ranked
            </md-text-button>
          </div>
        </div>
      </div>
    </li>
  );
}

function ReportReadyCard({runId}: {runId: string}) {
  return (
    <section
      className="rounded-xl border p-3 wb-fade-in"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor:
          'color-mix(in srgb, var(--color-th-success) 10%, var(--md-sys-color-surface-container-low))',
      }}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold">Report ready</p>
          <p
            className="text-xs"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            The polished report is available as a separate structured page.
          </p>
        </div>
        <Link
          to={`/runs/${runId}/report`}
          className="inline-flex items-center gap-1 text-sm font-semibold underline underline-offset-2"
          style={{color: 'var(--md-sys-color-primary)'}}
        >
          Open report page
          <md-icon style={{fontSize: '14px'}} aria-hidden="true">
            open_in_new
          </md-icon>
        </Link>
      </div>
    </section>
  );
}

function renderPanel({
  panelKind,
  history,
  activeRunId,
  openRun,
  evidence,
  systemStatus,
  focusedHypothesis,
  reviews,
  citations,
  matches,
  onClose,
}: {
  panelKind: PanelKind;
  history: Run[];
  activeRunId: string | null;
  openRun: (runId: string) => void;
  evidence: Evidence[];
  systemStatus: SystemStatus | null;
  focusedHypothesis: Hypothesis | null;
  reviews: Review[];
  citations: CitationRow[];
  matches: MatchRow[];
  onClose: () => void;
}) {
  if (!panelKind) return null;
  if (panelKind === 'history') {
    return (
      <PanelShell title="History" icon="history" onClose={onClose}>
        <HistoryPanel
          history={history}
          activeRunId={activeRunId}
          openRun={openRun}
        />
      </PanelShell>
    );
  }
  if (panelKind === 'knowledge') {
    return (
      <PanelShell title="Knowledge Base" icon="library_books" onClose={onClose}>
        <KnowledgePanel evidence={evidence} />
      </PanelShell>
    );
  }
  if (panelKind === 'settings') {
    return (
      <PanelShell title="Settings" icon="settings" onClose={onClose}>
        <SettingsPanel systemStatus={systemStatus} />
      </PanelShell>
    );
  }
  return (
    <PanelShell title="Why this ranked" icon="query_stats" onClose={onClose}>
      <WhyRankedPanel
        hypothesis={focusedHypothesis}
        reviews={reviews}
        citations={citations}
        matches={matches}
      />
    </PanelShell>
  );
}

function PanelShell({
  title,
  icon,
  children,
  onClose,
}: {
  title: string;
  icon: string;
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <aside
      className="min-h-[20rem] border-t p-4 sm:col-start-2 xl:col-start-auto xl:border-l xl:border-t-0 xl:overflow-y-auto"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface-container-low)',
      }}
    >
      <div className="mb-4 flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <md-icon style={{fontSize: '18px'}} aria-hidden="true">
            {icon}
          </md-icon>
          {title}
        </h2>
        <md-icon-button
          onclick={onClose as unknown as EventListener}
          aria-label="Close panel"
        >
          <md-icon aria-hidden="true">close</md-icon>
        </md-icon-button>
      </div>
      {children}
    </aside>
  );
}

function HistoryPanel({
  history,
  activeRunId,
  openRun,
}: {
  history: Run[];
  activeRunId: string | null;
  openRun: (runId: string) => void;
}) {
  if (!history.length) {
    return (
      <p
        className="text-sm"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
      >
        No previous runs yet.
      </p>
    );
  }
  return (
    <ol className="space-y-2">
      {history.slice(0, 12).map(run => (
        <li key={run.id}>
          <button
            type="button"
            onClick={() => openRun(run.id)}
            className="w-full rounded-md border p-2 text-left text-sm"
            style={{
              borderColor:
                activeRunId === run.id
                  ? 'var(--md-sys-color-primary)'
                  : 'var(--md-sys-color-outline-variant)',
              backgroundColor:
                activeRunId === run.id
                  ? 'var(--md-sys-color-secondary-container)'
                  : 'var(--md-sys-color-surface)',
            }}
          >
            <div className="mb-1 flex items-center justify-between gap-2">
              <RunStatusPill status={run.status} />
              <span
                className="text-xs"
                style={{color: 'var(--md-sys-color-on-surface-variant)'}}
              >
                {new Date(run.updated_at * 1000).toLocaleDateString()}
              </span>
            </div>
            <div className="line-clamp-2 font-medium leading-snug">
              {run.research_goal}
            </div>
          </button>
        </li>
      ))}
    </ol>
  );
}

function KnowledgePanel({evidence}: {evidence: Evidence[]}) {
  if (!evidence.length) {
    return (
      <p
        className="text-sm"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
      >
        Run evidence appears here after literature review.
      </p>
    );
  }
  return (
    <ol className="space-y-2">
      {evidence.slice(0, 10).map(item => (
        <li
          key={item.id}
          className="rounded-md border p-2 text-sm"
          style={{
            borderColor: 'var(--md-sys-color-outline-variant)',
            backgroundColor: 'var(--md-sys-color-surface)',
          }}
        >
          <div className="font-medium leading-snug">{item.title}</div>
          <div
            className="mt-1 text-xs"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            {item.source}
            {item.year ? ` · ${item.year}` : ''}
          </div>
        </li>
      ))}
    </ol>
  );
}

function SettingsPanel({systemStatus}: {systemStatus: SystemStatus | null}) {
  return (
    <div className="space-y-4 text-sm">
      <div
        className="rounded-md border p-3"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          backgroundColor: 'var(--md-sys-color-surface)',
        }}
      >
        <div className="mb-2 font-medium">Theme</div>
        <ThemeToggle />
      </div>
      <div
        className="rounded-md border p-3"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          backgroundColor: 'var(--md-sys-color-surface)',
        }}
      >
        <div className="font-medium">Runtime</div>
        <p
          className="mt-1 text-xs"
          style={{color: 'var(--md-sys-color-on-surface-variant)'}}
        >
          {systemStatus
            ? `${systemStatus.provider === 'mock' ? 'Mock' : 'Engine'} · ${systemStatus.model_name || 'model unset'}`
            : 'Checking runtime...'}
        </p>
      </div>
    </div>
  );
}

function WhyRankedPanel({
  hypothesis,
  reviews,
  citations,
  matches,
}: {
  hypothesis: Hypothesis | null;
  reviews: Review[];
  citations: CitationRow[];
  matches: MatchRow[];
}) {
  if (!hypothesis) {
    return (
      <p
        className="text-sm"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
      >
        Select a hypothesis to inspect its ranking rationale.
      </p>
    );
  }
  const hypReviews = reviews.filter(r => r.hypothesis_id === hypothesis.id);
  const hypCitations = citations.filter(c => c.hypothesis_id === hypothesis.id);
  const hypMatches = matches
    .filter(
      match =>
        match.winner_id === hypothesis.id || match.loser_id === hypothesis.id,
    )
    .slice(-3)
    .reverse();

  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide">
          Rank signal
        </div>
        <h3 className="mt-1 font-semibold leading-snug">{hypothesis.title}</h3>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Metric label="Elo" value={hypothesis.elo_rating} />
        <Metric label="Wins" value={hypothesis.win_count} />
        <Metric label="Evidence" value={hypCitations.length} />
      </div>
      {hypothesis.mechanism && (
        <PanelBlock title="Mechanism">{hypothesis.mechanism}</PanelBlock>
      )}
      {hypReviews[0] && (
        <PanelBlock title="Review rationale">
          {hypReviews[0].summary || hypReviews[0].critique}
        </PanelBlock>
      )}
      {hypMatches.length > 0 && (
        <PanelBlock title="Recent tournament rationale">
          <ul className="space-y-2">
            {hypMatches.map(match => (
              <li key={match.id}>{match.rationale}</li>
            ))}
          </ul>
        </PanelBlock>
      )}
      {hypCitations.length > 0 && (
        <PanelBlock title="Citation states">
          <ul className="space-y-1">
            {hypCitations.slice(0, 5).map(citation => (
              <li key={citation.id}>
                {citation.state}: {citation.claim}
              </li>
            ))}
          </ul>
        </PanelBlock>
      )}
    </div>
  );
}

function Metric({label, value}: {label: string; value: number}) {
  return (
    <div
      className="rounded-md border p-2"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface)',
      }}
    >
      <div
        className="text-[10px] font-semibold uppercase tracking-wide"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
      >
        {label}
      </div>
      <div className="mt-1 font-mono text-lg">{value}</div>
    </div>
  );
}

function PanelBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section
      className="rounded-md border p-3"
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        backgroundColor: 'var(--md-sys-color-surface)',
      }}
    >
      <div
        className="mb-1 text-xs font-semibold uppercase tracking-wide"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
      >
        {title}
      </div>
      <div className="leading-relaxed">{children}</div>
    </section>
  );
}

function formatEventName(type: string): string {
  if (type === 'status') return 'Status update';
  return type
    .replace(/[._]/g, ' ')
    .replace(/\b\w/g, char => char.toUpperCase());
}
