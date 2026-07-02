import '@material/web/icon/icon.js';

import {
  Fragment,
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {useLocation, useNavigate} from 'react-router-dom';
import {
  createRun,
  getHypotheses,
  listDemoRuns,
  listRuns,
  type Run,
  startRun,
} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {inferRunSpec, type InferredRunSpec, reviseRunSpec} from '../run_spec';
import {
  HOME_TOAST_CLASSES,
  HOME_WORKSPACE_CLASSES,
  HOME_WORKSPACE_MAIN_CLASSES,
} from './chat_home_classes';
import {
  CHAT_COLUMN_CLASSES,
  CHAT_COMPOSER_CLASSES,
  CHAT_TIMELINE_CLASSES,
} from './chat_setup_classes';
import {Composer} from './chat_composer';
import {HomeStage} from './chat_home_stage';
import {topEloFromHypotheses} from './home_recents';
import {
  ChatBubble,
  type ChatEntry,
  copyText,
  referenceSetupTitle,
  RunSpecCard,
  StartedSessionCard,
  type StartedSession,
} from './chat_timeline_cards';

interface TimelineItem {
  id: string;
  at: number;
  order: number;
  node: ReactNode;
}

type ChatWorkspaceLocationState = {
  cosciAction?: 'new-chat' | 'focus-composer';
};

function id(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function emitDiagnosticEvent({
  stage,
  run,
  level = 'info',
  payload = {},
}: {
  stage: string;
  run?: string;
  level?: 'info' | 'success' | 'error';
  payload?: Record<string, unknown>;
}) {
  window.dispatchEvent(
    new CustomEvent('cosci-diagnostic-event', {
      detail: {stage, run, level, payload},
    }),
  );
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
  const [confirmedSpec, setConfirmedSpec] = useState<InferredRunSpec | null>(
    null,
  );
  const [confirmedSpecCreatedAt, setConfirmedSpecCreatedAt] = useState<
    number | null
  >(null);
  const [startedSession, setStartedSession] = useState<StartedSession | null>(
    null,
  );
  const [isStarting, setIsStarting] = useState(false);
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [history, setHistory] = useState<Run[]>([]);
  const [homeScores, setHomeScores] = useState<Record<string, number | null>>(
    {},
  );
  const [error, setError] = useState<string | null>(null);
  const [showAllRecents, setShowAllRecents] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [pubmedEnabled, setPubmedEnabled] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const previousTimelineSignature = useRef('');

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(timer);
  }, [toast]);

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
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    setStartedSession(null);
    setIsStarting(false);
    setMessages([]);
    setError(null);
    setToast(null);
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
    const completedRuns = history
      .filter(run => run.status === 'completed')
      .slice(0, 10);
    if (!completedRuns.length) {
      setHomeScores({});
      return;
    }

    let cancelled = false;
    void Promise.all(
      completedRuns.map(async run => {
        try {
          const hypotheses = await getHypotheses(run.id);
          return [run.id, topEloFromHypotheses(hypotheses)] as const;
        } catch {
          return [run.id, null] as const;
        }
      }),
    ).then(entries => {
      if (cancelled) return;
      setHomeScores(Object.fromEntries(entries));
    });

    return () => {
      cancelled = true;
    };
  }, [history]);

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

  const hasConversation =
    messages.length > 0 ||
    Boolean(draftSpec) ||
    Boolean(confirmedSpec) ||
    Boolean(startedSession);

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

  function clearSessionState() {
    setDraftSpec(null);
    setDraftSpecCreatedAt(null);
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    setStartedSession(null);
  }

  function stageDraftSpec(
    spec: InferredRunSpec,
    createdAt = Date.now() / 1000,
  ) {
    setDraftSpec(spec);
    setDraftSpecCreatedAt(createdAt);
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    setStartedSession(null);
  }

  function handleRetryMessage(message: ChatEntry) {
    appendAssistant(message.content);
  }

  function handleEditMessage(message: ChatEntry) {
    setInput(message.content);
    focusComposer();
  }

  async function handleCopyRequest(message: ChatEntry) {
    await copyText(message.content);
    const copiedSpec = inferRunSpec(message.content);
    const createdAt = Date.now() / 1000;
    stageDraftSpec(copiedSpec, createdAt);
    setToast(null);
    emitDiagnosticEvent({
      stage: 'CHAT',
      run: referenceSetupTitle(copiedSpec.goal),
      payload: {event: 'prompt_copied_to_plan'},
    });
  }

  function handleRetryDraftSpec() {
    if (!draftSpec) return;
    stageDraftSpec(inferRunSpec(draftSpec.goal));
  }

  function handleCancelDraftSpec() {
    const title = draftSpec ? referenceSetupTitle(draftSpec.goal) : undefined;
    setInput('');
    clearSessionState();
    setMessages([]);
    setError(null);
    setToast('The session was canceled');
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: title,
      payload: {event: 'draft_cancelled'},
    });
  }

  function handleEditPlan(spec: InferredRunSpec) {
    stageDraftSpec(spec);
    focusComposer();
    emitDiagnosticEvent({
      stage: 'CHAT',
      run: referenceSetupTitle(spec.goal),
      payload: {event: 'plan_edit_requested'},
    });
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput('');
    setError(null);
    setToast(null);

    if (draftSpec) {
      const sentAt = appendUser(text);
      const next = reviseRunSpec(draftSpec, text);
      stageDraftSpec(next, sentAt + 0.001);
      appendAssistant(
        'I updated the run setup. Start it when the spec looks right.',
        sentAt + 0.002,
      );
      emitDiagnosticEvent({
        stage: 'CHAT',
        run: referenceSetupTitle(next.goal),
        payload: {event: 'draft_revised'},
      });
      return;
    }

    const sentAt = appendUser(text);
    const next = inferRunSpec(text);
    stageDraftSpec(next, sentAt + 0.001);
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: referenceSetupTitle(next.goal),
      payload: {event: 'draft_created'},
    });
  }

  async function handleStartRun() {
    if (!draftSpec) return;
    const specToStart = draftSpec;
    const specCreatedAt = draftSpecCreatedAt ?? Date.now() / 1000;
    setIsStarting(true);
    setError(null);
    setToast(null);
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: referenceSetupTitle(specToStart.goal),
      payload: {event: 'start_requested'},
    });
    try {
      const created = await createRun({
        research_goal: specToStart.goal,
        requirements: specToStart.requirements,
        attributes: specToStart.attributes,
        criteria: specToStart.criteria,
        focus: specToStart.focus,
        tier: specToStart.tier,
        enable_literature_review: pubmedEnabled,
        notes: [
          `Requirements: ${specToStart.requirements.join(' | ')}`,
          `Attributes: ${specToStart.attributes.join(' | ')}`,
          `Criteria: ${specToStart.criteria.join(' | ')}`,
          `Focus: ${specToStart.focus}`,
          `Tier: ${specToStart.tier}`,
        ].join('\n'),
      });
      const session: StartedSession = {
        id: created.id,
        title: referenceSetupTitle(specToStart.goal),
        at: Date.now() / 1000,
      };
      setConfirmedSpec(specToStart);
      setConfirmedSpecCreatedAt(specCreatedAt);
      setDraftSpec(null);
      setDraftSpecCreatedAt(null);
      await startRun(created.id);
      setStartedSession(session);
      await loadHistory();
      emitDiagnosticEvent({
        stage: 'LIFECYCLE',
        run: session.title,
        level: 'success',
        payload: {event: 'start_queued', run_id: created.id},
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      emitDiagnosticEvent({
        stage: 'LIFECYCLE',
        run: referenceSetupTitle(specToStart.goal),
        level: 'error',
        payload: {
          event: 'start_failed',
          message: err instanceof Error ? err.message : String(err),
        },
      });
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
      node: (
        <ChatBubble
          message={message}
          onEdit={() => handleEditMessage(message)}
          onCopyRequest={() => void handleCopyRequest(message)}
          onRetry={() => handleRetryMessage(message)}
        />
      ),
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
          onCancel={handleCancelDraftSpec}
          onEdit={() => handleEditPlan(draftSpec)}
          onRetry={() => handleRetryDraftSpec()}
          onStart={() => void handleStartRun()}
        />
      ),
    });
  }
  if (confirmedSpec && confirmedSpecCreatedAt !== null) {
    timelineItems.push({
      id: 'confirmed-spec',
      at: confirmedSpecCreatedAt,
      order: 50,
      node: (
        <RunSpecCard
          spec={confirmedSpec}
          isStarting={false}
          locked
          onFocusChange={() => undefined}
          onTierChange={() => undefined}
          onCancel={() => undefined}
          onEdit={() => handleEditPlan(confirmedSpec)}
          onRetry={() => {
            stageDraftSpec(confirmedSpec);
          }}
          onStart={() => undefined}
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
          onRetry={() =>
            setStartedSession(current =>
              current ? {...current, at: Date.now() / 1000} : current,
            )
          }
          onNewTopic={() => {
            resetWorkspace();
            focusComposer();
          }}
        />
      ),
    });
  }
  timelineItems.sort((a, b) => a.at - b.at || a.order - b.order);
  const timelineSignature = timelineItems
    .map(item => `${item.id}:${item.at}`)
    .join('|');
  const latestTimelineItemId =
    timelineItems.length > 0 ? timelineItems[timelineItems.length - 1].id : '';
  const timelineAnchorMode = startedSession
    ? 'bottom'
    : latestTimelineItemId === 'draft-spec' ||
        latestTimelineItemId === 'confirmed-spec'
      ? 'top'
      : 'bottom';

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || previousTimelineSignature.current === timelineSignature) {
      return;
    }
    previousTimelineSignature.current = timelineSignature;
    const timeout = window.setTimeout(() => {
      scroller.scrollTop =
        timelineAnchorMode === 'top' ? 0 : scroller.scrollHeight;
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [timelineAnchorMode, timelineSignature]);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!startedSession || !scroller) {
      return;
    }
    const timeout = window.setTimeout(() => {
      scroller.scrollTop = scroller.scrollHeight;
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [startedSession]);

  return (
    <div className={HOME_WORKSPACE_CLASSES}>
      <main className={HOME_WORKSPACE_MAIN_CLASSES}>
        {!hasConversation ? (
          <HomeStage
            input={input}
            setInput={setInput}
            pubmedEnabled={pubmedEnabled}
            onPubmedEnabledChange={setPubmedEnabled}
            onSubmit={handleSubmit}
            runs={history}
            scoresByRunId={homeScores}
            showAllRecents={showAllRecents}
            onToggleShowAll={() => setShowAllRecents(current => !current)}
          />
        ) : (
          <>
            <section ref={scrollRef} className={CHAT_TIMELINE_CLASSES}>
              <div className={CHAT_COLUMN_CLASSES}>
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
            <div className={CHAT_COMPOSER_CLASSES}>
              <div className={CHAT_COLUMN_CLASSES}>
                <Composer
                  input={input}
                  setInput={setInput}
                  setupDraftMode={Boolean(draftSpec || startedSession)}
                  disabled={isStarting}
                  pubmedEnabled={pubmedEnabled}
                  onPubmedEnabledChange={setPubmedEnabled}
                  onSubmit={handleSubmit}
                />
              </div>
            </div>
          </>
        )}
        {toast && (
          <div className={HOME_TOAST_CLASSES} role="status">
            {toast}
          </div>
        )}
      </main>
    </div>
  );
}
