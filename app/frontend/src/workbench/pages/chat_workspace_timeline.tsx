import {type Dispatch, type ReactNode, type SetStateAction} from 'react';
import {type NavigateFunction} from 'react-router-dom';
import {type RunFocus, type RunTier} from '@/api/runs';
import {MarkdownMessage} from '@/components/markdown_message';
import {type InferredRunSpec} from '../run_spec';
import {type SpecStage} from '../hooks/chat_session_types';
import {
  type ChatEntry,
  ChatBubble,
  RunSpecCard,
  type StartedSession,
  StartedSessionCard,
} from './chat_timeline_cards';
import {ThoughtsDisclosure} from './chat_timeline_thoughts';

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

/**
 * The Agent's reply as it is being written.
 *
 * Rendered in the same bubble the finished turn lands in, so the reply does
 * not visibly move or restyle when the stream resolves -- the durable turn
 * simply replaces it. Not announced: the resolved message is what a screen
 * reader should read, once, rather than a partial sentence per token.
 */
function AgentDraft({draft}: {draft: string}) {
  return (
    <div className="reference-bubble-row assistant" aria-hidden="true">
      <MarkdownMessage
        content={draft}
        className="min-w-0 text-base leading-[1.45] text-cosci-fg"
      />
    </div>
  );
}

// The Agent's thinking and its reply-in-progress, shown at the tail of the
// timeline while it composes an interview turn; timestamped "now" so they sort
// after the just-sent user message, and cleared the moment the turn resolves.
// The thinking stays visible under the reply because a thinking model has
// finished reasoning before its first answer token, so the trail is a record
// of how the reply was reached rather than something still filling.
//
// It is the same disclosure the finished turn keeps, in its live state: one
// control that stops counting and closes, rather than one control replaced by
// another as the turn resolves.
function thinkingTimelineItems({
  isAwaitingAgent,
  agentReasoning,
  agentDraft,
}: Pick<
  BuildTimelineItemsArgs,
  'isAwaitingAgent' | 'agentReasoning' | 'agentDraft'
>): TimelineItem[] {
  if (!isAwaitingAgent) return [];
  const items: TimelineItem[] = [
    {
      id: 'agent-thinking',
      at: Date.now() / 1000,
      order: 45,
      node: <ThoughtsDisclosure reasoning={agentReasoning} live />,
    },
  ];
  if (agentDraft) {
    items.push({
      id: 'agent-draft',
      at: Date.now() / 1000,
      order: 46,
      node: <AgentDraft draft={agentDraft} />,
    });
  }
  return items;
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
      isStarting={isStarting}
      intro={draft.intro}
      introFallback={draft.fallback}
      onFocusChange={(focus: RunFocus) => updateDraftSpec(setDraft, {focus})}
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
    // The completing turn's thinking, above the plan it produced -- that turn
    // has no bubble of its own (its message becomes the card's lead-in), so
    // without this its reasoning would be the only one silently dropped.
    ...(draft.reasoning
      ? [
          {
            id: 'draft-spec-thoughts',
            at: draft.createdAt,
            order: 49,
            node: <ThoughtsDisclosure reasoning={draft.reasoning} />,
          },
        ]
      : []),
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
    ...draftTimelineItems(args),
    ...confirmedSpecTimelineItems(args),
    ...startedTimelineItems(args),
  ];
  // Chronological order, with `order` breaking ties between items created in
  // the same tick (e.g. a message and a spec card stamped at the same time).
  timelineItems.sort((a, b) => a.at - b.at || a.order - b.order);
  return timelineItems;
}
