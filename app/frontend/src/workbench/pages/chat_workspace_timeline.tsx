import {
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useEffect,
  useRef,
} from 'react';
import {type NavigateFunction} from 'react-router-dom';
import {type RunFocus, type RunTier} from '@/api/runs';
import {type InferredRunSpec} from '../run_spec';
import {type SpecStage} from '../hooks/chat_session_types';
import {
  type ChatEntry,
  ChatBubble,
  RunSpecCard,
  type StartedSession,
  StartedSessionCard,
} from './chat_timeline_cards';

/**
 * One renderable entry in the chat timeline.
 *
 * Local chat messages, the draft/confirmed run-spec cards, and the
 * started-session card are all normalized into this shape so they can be
 * merged and sorted by time.
 */
export interface TimelineItem {
  id: string;
  at: number;
  order: number;
  node: ReactNode;
}

// Fixed ids of the (at most one each) run-spec card entries. The scroll hook
// (chat_workspace_scroll.ts) anchors these tall cards to the top when they
// arrive, so it matches on the same constants.
export const DRAFT_SPEC_ITEM_ID = 'draft-spec';
export const CONFIRMED_SPEC_ITEM_ID = 'confirmed-spec';

/**
 * Dependencies buildTimelineItems (and the per-category helpers below) need to
 * render each kind of timeline entry.
 *
 * See ChatWorkspace's `session` plus its own navigate/resetWorkspace/
 * focusComposer for where these come from.
 */
export interface BuildTimelineItemsArgs {
  messages: ChatEntry[];
  handleEditMessage: (message: ChatEntry) => void;
  handleCopyRequest: (message: ChatEntry) => Promise<void>;
  handleRetryMessage: (message: ChatEntry) => void;
  draft: SpecStage | null;
  setDraft: Dispatch<SetStateAction<SpecStage | null>>;
  isStarting: boolean;
  isAwaitingAgent: boolean;
  agentReasoning: string;
  handleCancelDraftSpec: () => void;
  handleEditPlan: (spec: InferredRunSpec) => void;
  handleRetryDraftSpec: () => void;
  handleStartRun: () => Promise<void>;
  confirmed: SpecStage | null;
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void;
  startedSession: StartedSession | null;
  setStartedSession: Dispatch<SetStateAction<StartedSession | null>>;
  navigate: NavigateFunction;
  resetWorkspace: () => void;
  focusComposer: () => void;
}

// Each chat message becomes a ChatBubble; `order` preserves message array
// order as a tiebreaker when timestamps collide.
function messageTimelineItems({
  messages,
  handleEditMessage,
  handleCopyRequest,
  handleRetryMessage,
}: Pick<
  BuildTimelineItemsArgs,
  'messages' | 'handleEditMessage' | 'handleCopyRequest' | 'handleRetryMessage'
>): TimelineItem[] {
  return messages.map((message, index) => ({
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
  }));
}

/**
 * The Agent's live chain of thought while it composes an interview turn.
 *
 * The text is the model's own reasoning, streamed as it is produced: DeepSeek
 * emits its whole chain of thought before the first token of the answer, so
 * the trail fills while the scientist waits. Until the first fragment lands
 * there is nothing real to show, so the label stands alone.
 */
function AgentThinking({reasoning}: {reasoning: string}) {
  const trailRef = useRef<HTMLDivElement>(null);

  // Follow the newest thought as the model writes, like a log tail.
  useEffect(() => {
    const trail = trailRef.current;
    if (trail) trail.scrollTop = trail.scrollHeight;
  }, [reasoning]);

  return (
    <div className="px-1 py-2" role="status" aria-live="polite">
      <span className="animate-pulse text-sm text-th-muted-fg">Thinking…</span>
      {reasoning && (
        <div
          ref={trailRef}
          // Capped and scrollable: reasoning can outrun the viewport, and it
          // must never push the composer or the arriving reply off screen.
          className="mt-2 max-h-24 overflow-y-auto border-l-2 border-th-border pl-3 text-xs leading-relaxed whitespace-pre-wrap text-th-muted-fg"
        >
          {reasoning}
        </div>
      )}
    </div>
  );
}

// The Agent's thinking, shown at the tail of the timeline while it composes its
// reply to an interview turn; timestamped "now" so it sorts after the just-sent
// user message, and cleared the moment the response arrives.
function thinkingTimelineItems({
  isAwaitingAgent,
  agentReasoning,
}: Pick<
  BuildTimelineItemsArgs,
  'isAwaitingAgent' | 'agentReasoning'
>): TimelineItem[] {
  if (!isAwaitingAgent) return [];
  return [
    {
      id: 'agent-thinking',
      at: Date.now() / 1000,
      order: 45,
      node: <AgentThinking reasoning={agentReasoning} />,
    },
  ];
}

// Merges a partial spec edit into the pending draft, leaving a null draft
// (already confirmed/cancelled) untouched.
function updateDraftSpec(
  setDraft: Dispatch<SetStateAction<SpecStage | null>>,
  patch: Partial<InferredRunSpec>,
): void {
  setDraft(current =>
    current ? {...current, spec: {...current.spec, ...patch}} : current,
  );
}

// Editable draft run spec awaiting confirmation: focus/tier edits write
// straight back into draftSpec, and cancel/edit/retry/start delegate to the
// session hook's handlers.
function draftTimelineItems({
  draft,
  isStarting,
  setDraft,
  handleCancelDraftSpec,
  handleEditPlan,
  handleRetryDraftSpec,
  handleStartRun,
}: Pick<
  BuildTimelineItemsArgs,
  | 'draft'
  | 'isStarting'
  | 'setDraft'
  | 'handleCancelDraftSpec'
  | 'handleEditPlan'
  | 'handleRetryDraftSpec'
  | 'handleStartRun'
>): TimelineItem[] {
  if (!draft) return [];
  return [
    {
      id: DRAFT_SPEC_ITEM_ID,
      at: draft.createdAt,
      order: 50,
      node: (
        <RunSpecCard
          spec={draft.spec}
          isStarting={isStarting}
          intro={draft.intro}
          onFocusChange={(focus: RunFocus) =>
            updateDraftSpec(setDraft, {focus})
          }
          onTierChange={(tier: RunTier) => updateDraftSpec(setDraft, {tier})}
          onNotificationChange={(enabled, email) =>
            updateDraftSpec(setDraft, {
              notifyOnCompletion: enabled,
              completionEmail: email,
            })
          }
          onCancel={handleCancelDraftSpec}
          onEdit={() => handleEditPlan(draft.spec)}
          onRetry={() => handleRetryDraftSpec()}
          onStart={() => void handleStartRun()}
        />
      ),
    },
  ];
}

// Read-only confirmed spec once the plan has been locked in (e.g. after an
// edit round-trip): all mutation handlers are no-ops and `locked` disables
// the option cards; retrying re-stages it as an editable draft again.
function confirmedSpecTimelineItems({
  confirmed,
  handleEditPlan,
  stageDraftSpec,
}: Pick<
  BuildTimelineItemsArgs,
  'confirmed' | 'handleEditPlan' | 'stageDraftSpec'
>): TimelineItem[] {
  if (!confirmed) return [];
  return [
    {
      id: CONFIRMED_SPEC_ITEM_ID,
      at: confirmed.createdAt,
      order: 50,
      node: (
        <RunSpecCard
          spec={confirmed.spec}
          isStarting={false}
          locked
          onFocusChange={() => undefined}
          onTierChange={() => undefined}
          onNotificationChange={() => undefined}
          onCancel={() => undefined}
          onEdit={() => handleEditPlan(confirmed.spec)}
          onRetry={() => {
            stageDraftSpec(confirmed.spec);
          }}
          onStart={() => undefined}
        />
      ),
    },
  ];
}

// Terminal timeline entry once the backend run has actually started; opening
// it navigates to the run detail page, "retry" just bumps its timestamp so
// it re-sorts to the current time.
function startedTimelineItems({
  startedSession,
  setStartedSession,
  navigate,
  resetWorkspace,
  focusComposer,
}: Pick<
  BuildTimelineItemsArgs,
  | 'startedSession'
  | 'setStartedSession'
  | 'navigate'
  | 'resetWorkspace'
  | 'focusComposer'
>): TimelineItem[] {
  if (!startedSession) return [];
  return [
    {
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
    },
  ];
}

/**
 * Merges every timeline-worthy piece of session state (messages, draft spec,
 * confirmed spec, started session) into one list of TimelineItems, each
 * carrying the rendered card/bubble node plus enough metadata to sort them,
 * and returns them in chronological order.
 *
 * @param args The session state plus navigation/reset/focus callbacks needed
 *   to render each kind of timeline entry.
 * @returns The timeline items in chronological order.
 */
export function buildTimelineItems(
  args: BuildTimelineItemsArgs,
): TimelineItem[] {
  const timelineItems: TimelineItem[] = [
    ...messageTimelineItems(args),
    ...thinkingTimelineItems(args),
    ...draftTimelineItems(args),
    ...confirmedSpecTimelineItems(args),
    ...startedTimelineItems(args),
  ];
  // Chronological order, with `order` breaking ties between items created in
  // the same tick (e.g. a message and a spec card stamped at the same time).
  timelineItems.sort((a, b) => a.at - b.at || a.order - b.order);
  return timelineItems;
}
