import {type Dispatch, type ReactNode, type SetStateAction} from 'react';
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
import {AssistantMessage} from './chat_timeline_bubble';

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
  /**
   * Extra input to the scroll signature, for an item whose content grows in
   * place rather than by another item arriving (see chat_workspace_scroll.ts).
   * Without it such growth is invisible to the auto-scroll, since neither the
   * item's id nor its timestamp changes as it fills.
   */
  revision?: string | number;
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
  handleEditMessage: (message: ChatEntry, content: string) => void;
  handleCopyRequest: (message: ChatEntry) => Promise<void>;
  handleRetryMessage: (message: ChatEntry) => void;
  draft: SpecStage | null;
  setDraft: Dispatch<SetStateAction<SpecStage | null>>;
  isStarting: boolean;
  isAwaitingAgent: boolean;
  agentReasoning: string;
  agentDraft: string;
  handleCancelDraftSpec: () => void;
  handleEditPlan: (spec: InferredRunSpec) => void;
  handleRetryDraftSpec: () => void;
  handleStartRun: () => Promise<void>;
  confirmed: SpecStage | null;
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void;
  startedSession: StartedSession | null;
  navigate: NavigateFunction;
  resetWorkspace: () => void;
  focusComposer: () => void;
}

// Each chat message becomes a ChatBubble; `order` preserves message array
// order as a tiebreaker when timestamps collide.
//
// A message is revisable only when it has a durable turn behind it, no turn
// is already in flight, and the conversation has not been committed to a run:
// rewinding the interview after that would clear the started card off the
// timeline while the run it points at kept going.
function messageTimelineItems({
  messages,
  handleEditMessage,
  handleCopyRequest,
  handleRetryMessage,
  isAwaitingAgent,
  startedSession,
}: Pick<
  BuildTimelineItemsArgs,
  | 'messages'
  | 'handleEditMessage'
  | 'handleCopyRequest'
  | 'handleRetryMessage'
  | 'isAwaitingAgent'
  | 'startedSession'
>): TimelineItem[] {
  const revisable = !isAwaitingAgent && !startedSession;
  return messages.map((message, index) => ({
    id: `local-message-${message.id}`,
    at: message.created_at,
    order: index,
    node: (
      <ChatBubble
        message={message}
        revisable={revisable && message.turnId !== undefined}
        onSubmitEdit={content => handleEditMessage(message, content)}
        onCopyRequest={() => void handleCopyRequest(message)}
        onRetry={() => handleRetryMessage(message)}
      />
    ),
  }));
}

// The turn the Agent is writing, as one message: its thinking and its reply
// in progress are parts of the same AssistantMessage the settled turn lands
// in, so nothing about the message moves or re-spaces when the stream
// resolves. They were two timeline entries of their own, which put the
// column's 1.15rem gap between the disclosure and the reply -- a gap that
// vanished the moment the turn settled into a bubble and the two became
// siblings inside it.
//
// Timestamped "now" so it sorts after the just-sent user message, and gone
// the moment the turn resolves. The thinking stays visible under the reply
// because a thinking model has finished reasoning before its first answer
// token, so the trail is a record of how the reply was reached rather than
// something still filling.
//
// Interview-only: once a run has started, `isAwaitingAgent` covers a run
// Q&A turn instead (see qaAnswerTimelineItems below), which renders its own
// live reasoning disclosure the same way -- the run's Q&A stream carries a
// `reasoning` frame too (qa.py::stream_answer), it just arrives into a
// differently-gated timeline item since a Q&A turn has no plan or session
// card riding along with it.
function thinkingTimelineItems({
  startedSession,
  isAwaitingAgent,
  agentReasoning,
  agentDraft,
}: Pick<
  BuildTimelineItemsArgs,
  'startedSession' | 'isAwaitingAgent' | 'agentReasoning' | 'agentDraft'
>): TimelineItem[] {
  if (startedSession || !isAwaitingAgent) return [];
  return [
    {
      id: 'agent-turn-in-flight',
      at: Date.now() / 1000,
      order: 45,
      revision: agentDraft.length + agentReasoning.length,
      node: (
        <AssistantMessage
          content={agentDraft}
          reasoning={agentReasoning}
          live
          streaming
        />
      ),
    },
  ];
}

// The run Q&A answer as it streams in, in the same message an interview
// turn's live reply grows in -- including its "Thinking" disclosure, since
// a Q&A turn carries reasoning too (see thinkingTimelineItems). Renders
// nothing until either the model's reasoning or its prose starts arriving,
// so a question in flight shows only the Stop control until there is
// something to grow.
function qaAnswerTimelineItems({
  startedSession,
  isAwaitingAgent,
  agentReasoning,
  agentDraft,
}: Pick<
  BuildTimelineItemsArgs,
  'startedSession' | 'isAwaitingAgent' | 'agentReasoning' | 'agentDraft'
>): TimelineItem[] {
  if (!startedSession || !isAwaitingAgent) return [];
  if (!agentDraft && !agentReasoning) return [];
  return [
    {
      id: 'qa-answer-draft',
      at: Date.now() / 1000,
      order: 46,
      revision: agentDraft.length + agentReasoning.length,
      node: (
        <AssistantMessage
          content={agentDraft}
          reasoning={agentReasoning}
          live
          streaming
        />
      ),
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

// Builds the draft RunSpecCard node: focus/tier edits write straight back
// into draftSpec, and cancel/edit/retry/start delegate to the session hook's
// handlers.
type DraftSpecCardArgs = Omit<
  Pick<
    BuildTimelineItemsArgs,
    | 'draft'
    | 'isStarting'
    | 'setDraft'
    | 'handleCancelDraftSpec'
    | 'handleEditPlan'
    | 'handleRetryDraftSpec'
    | 'handleStartRun'
  >,
  'draft'
> & {draft: SpecStage};

function draftSpecCardNode({
  draft,
  isStarting,
  setDraft,
  handleCancelDraftSpec,
  handleEditPlan,
  handleRetryDraftSpec,
  handleStartRun,
}: DraftSpecCardArgs): ReactNode {
  return (
    <RunSpecCard
      spec={draft.spec}
      anchorId={DRAFT_SPEC_ITEM_ID}
      isStarting={isStarting}
      intro={draft.intro}
      introReasoning={draft.reasoning}
      introFallback={draft.fallback}
      onFocusChange={(focus: RunFocus) => updateDraftSpec(setDraft, {focus})}
      onTierChange={(tier: RunTier) => updateDraftSpec(setDraft, {tier})}
      onNotificationChange={(enabled, email) =>
        updateDraftSpec(setDraft, {
          notifyOnCompletion: enabled,
          completionEmail: email,
        })
      }
      onFieldsChange={patch => updateDraftSpec(setDraft, patch)}
      onCancel={handleCancelDraftSpec}
      onEdit={() => handleEditPlan(draft.spec)}
      onRetry={() => handleRetryDraftSpec()}
      onStart={() => void handleStartRun()}
    />
  );
}

// Editable draft run spec awaiting confirmation timeline entry, wrapping
// draftSpecCardNode above with its TimelineItem metadata.
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
      node: draftSpecCardNode({
        draft,
        isStarting,
        setDraft,
        handleCancelDraftSpec,
        handleEditPlan,
        handleRetryDraftSpec,
        handleStartRun,
      }),
    },
  ];
}

// Read-only confirmed spec once the plan has been locked in (e.g. after an
// edit round-trip): all mutation handlers are no-ops and `locked` disables
// the option cards; retrying re-stages it as an editable draft again.
//
// It is the same turn the draft card was, so it renders with the same
// closing message, thinking and fallback marker. Freezing the plan used to
// drop all three, which read as the Agent's reply vanishing (and its
// thinking jumping below the plan) the instant Start research was clicked.
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
          intro={confirmed.intro}
          introReasoning={confirmed.reasoning}
          introFallback={confirmed.fallback}
          locked
          onFocusChange={() => undefined}
          onTierChange={() => undefined}
          onNotificationChange={() => undefined}
          onFieldsChange={() => undefined}
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

// How much of the started card has arrived, as one value the scroll
// signature can compare.
//
// The Agent's reply and its chain of thought both stream into this card,
// growing it a fragment at a time under a fixed id and timestamp -- so
// neither shows up as a timeline change on its own. The announcing flag
// rides along too, because the session block appears when it clears (see
// StartedSessionCard), which grows the card without adding a character to
// either.
function startedCardRevision(session: StartedSession): string {
  const intro = session.intro?.length ?? 0;
  const reasoning = session.reasoning?.length ?? 0;
  return `${intro}:${reasoning}:${Boolean(session.announcing)}`;
}

// Terminal timeline entry once the backend run has actually started; the card
// links to the run detail page (a URL, not a handler, so a middle- or
// cmd-click opens it in a new tab).
function startedTimelineItems({
  startedSession,
  navigate,
  resetWorkspace,
  focusComposer,
}: Pick<
  BuildTimelineItemsArgs,
  'startedSession' | 'navigate' | 'resetWorkspace' | 'focusComposer'
>): TimelineItem[] {
  if (!startedSession) return [];
  return [
    {
      id: `started-session-${startedSession.id}`,
      at: startedSession.at,
      order: 60,
      revision: startedCardRevision(startedSession),
      node: (
        <StartedSessionCard
          session={startedSession}
          href={`/runs/${startedSession.id}/details`}
          onNewTopic={() => {
            // Leaving /chats/:id is the part that makes this stick. Clearing
            // the session alone left the finished chat's id in the URL, and
            // the rehydrator re-attached its run the moment the chat and run
            // lists next resolved -- the workspace blanked and then put the
            // same started card straight back, which reads as a dead button.
            resetWorkspace();
            void navigate('/');
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
    ...qaAnswerTimelineItems(args),
    ...draftTimelineItems(args),
    ...confirmedSpecTimelineItems(args),
    ...startedTimelineItems(args),
  ];
  // Chronological order, with `order` breaking ties between items created in
  // the same tick (e.g. a message and a spec card stamped at the same time).
  timelineItems.sort((a, b) => a.at - b.at || a.order - b.order);
  return timelineItems;
}
