import {
  Fragment,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {useLocation, useNavigate} from 'react-router-dom';
import {conciseTitle} from '@/lib/text';
import {useToast} from '../hooks/use_toast';
import {useRunHistory} from '../hooks/use_run_history';
import {useChatSession} from '../hooks/use_chat_session';
import {
  HOME_TOAST_ACTION_CLASSES,
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
import {
  ChatBubble,
  RunSpecCard,
  StartedSessionCard,
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

/**
 * Renders the chat-first Co-Scientist workspace.
 */
export function ChatWorkspace() {
  const location = useLocation();
  const navigate = useNavigate();
  const [showAllRecents, setShowAllRecents] = useState(false);
  const [pubmedEnabled, setPubmedEnabled] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const previousTimelineSignature = useRef('');

  const {toast, setToast} = useToast();
  const {history, homeScores, reloadHistory} = useRunHistory();

  const focusComposer = useCallback(() => {
    window.requestAnimationFrame(() => {
      const composer = document.querySelector<HTMLTextAreaElement>(
        '.reference-composer textarea',
      );
      composer?.focus();
    });
  }, []);

  const session = useChatSession({
    reloadHistory,
    focusComposer,
    setToast,
    pubmedEnabled,
  });
  const {
    input,
    setInput,
    draftSpec,
    setDraftSpec,
    draftSpecCreatedAt,
    confirmedSpec,
    confirmedSpecCreatedAt,
    startedSession,
    setStartedSession,
    isStarting,
    messages,
    error,
    hasConversation,
    resetSession,
    stageDraftSpec,
    handleRetryMessage,
    handleEditMessage,
    handleCopyRequest,
    handleRetryDraftSpec,
    handleCancelDraftSpec,
    handleEditPlan,
    handleSubmit,
    handleStartRun,
  } = session;

  const resetWorkspace = useCallback(() => {
    resetSession();
    setToast(null);
    void reloadHistory();
  }, [reloadHistory, resetSession, setToast]);

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
            <span>{toast.message}</span>
            {toast.action && (
              <button
                type="button"
                className={HOME_TOAST_ACTION_CLASSES}
                onClick={toast.action.onClick}
              >
                {toast.action.label}
              </button>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
