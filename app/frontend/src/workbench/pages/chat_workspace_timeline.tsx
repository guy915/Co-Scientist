import {type Dispatch, type ReactNode, type SetStateAction} from 'react';
import {type NavigateFunction} from 'react-router-dom';
import {type RunFocus, type RunTier} from '@/api/runs';
import {type InferredRunSpec} from '../run_spec';
import {
  type LinkedDraftRecovery,
  type SpecStage,
} from '../hooks/use_chat_session';
import {
  type ChatEntry,
  ChatBubble,
  AssistantMessage,
} from './chat_timeline_bubble';
import {RunSpecCard} from './chat_timeline_run_spec_card';
import {
  type StartedSession,
  StartedSessionCard,
} from './chat_timeline_run_spec_card';

export interface TimelineItem {
  id: string;
  at: number;
  order: number;
  node: ReactNode;
  // Revision makes in-place streamed growth visible to scrolling despite
  // unchanged item id and timestamp.
  revision?: string | number;
}

export const DRAFT_SPEC_ITEM_ID = 'draft-spec';
export const CONFIRMED_SPEC_ITEM_ID = 'confirmed-spec';

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
  handleRetryDraftSpec: () => void;
  handleStartRun: () => Promise<void>;
  confirmed: SpecStage | null;
  linkedDraftRecovery: LinkedDraftRecovery;
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void;
  startedSession: StartedSession | null;
  navigate: NavigateFunction;
  resetWorkspace: () => void;
  focusComposer: () => void;
}

// Only durable, uncommitted turns can rewind; revising after start would erase
// the card while its run continued.
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

// Keep reasoning and prose in the same row so settlement cannot change spacing
// or their relative position.
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

function updateDraftSpec(
  setDraft: Dispatch<SetStateAction<SpecStage | null>>,
  patch: Partial<InferredRunSpec>,
): void {
  setDraft(current =>
    current ? {...current, spec: {...current.spec, ...patch}} : current,
  );
}

type DraftSpecCardArgs = Omit<
  Pick<
    BuildTimelineItemsArgs,
    | 'draft'
    | 'isStarting'
    | 'setDraft'
    | 'handleCancelDraftSpec'
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
      onRetry={() => handleRetryDraftSpec()}
      onStart={() => void handleStartRun()}
    />
  );
}

function draftTimelineItems({
  draft,
  isStarting,
  setDraft,
  handleCancelDraftSpec,
  handleRetryDraftSpec,
  handleStartRun,
}: Pick<
  BuildTimelineItemsArgs,
  | 'draft'
  | 'isStarting'
  | 'setDraft'
  | 'handleCancelDraftSpec'
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
        handleRetryDraftSpec,
        handleStartRun,
      }),
    },
  ];
}

// Confirmed plans retain the same closing reply, reasoning and fallback
// provenance as their draft.
function confirmedSpecTimelineItems({
  confirmed,
  linkedDraftRecovery,
  handleStartRun,
  isStarting,
  stageDraftSpec,
}: Pick<
  BuildTimelineItemsArgs,
  | 'confirmed'
  | 'linkedDraftRecovery'
  | 'handleStartRun'
  | 'isStarting'
  | 'stageDraftSpec'
>): TimelineItem[] {
  if (!confirmed) return [];
  const {canContinueLinkedDraft, spec, status, retryStatusLookup} =
    linkedDraftRecovery;
  return [
    {
      id: CONFIRMED_SPEC_ITEM_ID,
      at: confirmed.createdAt,
      order: 50,
      node: (
        <RunSpecCard
          spec={canContinueLinkedDraft && spec ? spec : confirmed.spec}
          isStarting={isStarting}
          recoveryAction={canContinueLinkedDraft}
          recoveryLookupStatus={status}
          onRetryStatusLookup={retryStatusLookup}
          intro={confirmed.intro}
          introReasoning={confirmed.reasoning}
          introFallback={confirmed.fallback}
          locked
          onFocusChange={() => undefined}
          onTierChange={() => undefined}
          onNotificationChange={() => undefined}
          onFieldsChange={() => undefined}
          onCancel={() => undefined}
          onRetry={() => {
            stageDraftSpec(confirmed.spec);
          }}
          onStart={
            canContinueLinkedDraft
              ? () => void handleStartRun()
              : () => undefined
          }
        />
      ),
    },
  ];
}

// Include reasoning, reply and announcing state in the signature: each can
// grow the same fixed-id card.
function startedCardRevision(session: StartedSession): string {
  const intro = session.intro?.length ?? 0;
  const reasoning = session.reasoning?.length ?? 0;
  return `${intro}:${reasoning}:${Boolean(session.announcing)}`;
}

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
            // Leave the old chat route when clearing; otherwise history
            // rehydration immediately reattaches its started run.
            resetWorkspace();
            void navigate('/');
            focusComposer();
          }}
        />
      ),
    },
  ];
}

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
  timelineItems.sort((a, b) => a.at - b.at || a.order - b.order);
  return timelineItems;
}
