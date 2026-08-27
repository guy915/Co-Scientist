import {useState, type ReactNode} from 'react';
import {type QaSource} from '@/api/runs';
import {MarkdownMessage} from '@/components/markdown_message';
import {
  CHAT_BUBBLE_ROW_CLASSES,
  CHAT_BUBBLE_USER_ROW_CLASSES,
  MESSAGE_ATTACHMENT_CLASSES,
  MODEL_BUBBLE_CLASSES,
  MODEL_BUBBLE_TEXT_CLASSES,
  USER_BUBBLE_CLASSES,
} from './chat_setup_classes';
import {
  BubbleText,
  useCollapsibleBubbleText,
} from './chat_timeline_bubble_text';
import {
  MessageActionRow,
  requestActions,
  responseActions,
  type MessageAction,
} from './chat_timeline_message_actions';
import {BubbleEditor} from './chat_timeline_bubble_editor';
import {ThoughtsDisclosure} from './chat_timeline_thoughts';

/**
 * One rendered chat-timeline message (either the user's or the
 * assistant's).
 */
export interface ChatEntry {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /**
   * The Agent's chain of thought for this turn, when the model produced one.
   * Kept with the message rather than discarded when the reply lands, so the
   * reasoning stays readable (and stays in the model's own context).
   */
  reasoning?: string;
  /**
   * The durable interview turn this bubble renders, when it has one. Absent
   * for bubbles the browser added on its own (an optimistic turn still in
   * flight, the "Start research" line), which is exactly the set that cannot
   * be edited or retried -- there is no server-side turn to replace.
   */
  turnId?: number;
  /**
   * True when the interview's deterministic fallback authored this message
   * because no model could be reached. Rendered as a quiet notice so
   * scripted questions are never silently passed off as model output.
   */
  fallback?: boolean;
  created_at: number;
  /**
   * The evidence manifest backing a run Q&A answer, when it cited any
   * sources (see `runs_qa.ts::askRunQuestion`'s `onSources` sink). Persisted
   * on the entry so a reload keeps it, but nothing renders it yet -- there
   * is no citation-chip surface designed for the chat timeline, and this
   * codebase's existing reference lists (run_detail_learning_references.tsx)
   * are built for a run's full evidence page, not a per-answer chat bubble.
   */
  sources?: QaSource[];
}

// The quiet marker copy for a fallback-authored turn: honest about what the
// scientist is reading without alarming them. Shares the ThoughtsDisclosure
// summary's muted typography deliberately -- it is metadata, not content.
export const FALLBACK_NOTICE_TEXT = 'Guided questions (no model available)';

const FALLBACK_NOTICE_CLASSES = 'mb-1 text-xs font-medium text-cosci-muted';

/**
 * The quiet signal that a turn came from the interview's deterministic
 * fallback (no model configured or reachable) rather than the model. Shown
 * above fallback-authored assistant turns and the plan card's fallback
 * lead-in; model-driven turns render nothing.
 */
export function FallbackTurnNotice() {
  return <p className={FALLBACK_NOTICE_CLASSES}>{FALLBACK_NOTICE_TEXT}</p>;
}

/**
 * Wrapper for an inline attachment an assistant message can carry: extra
 * content rendered in the message's own flow, below its markdown body and
 * above its action row (see {@link AssistantMessage}'s `attachment` prop).
 * The research-plan document (chat_timeline_run_spec_card.tsx) and the
 * started-session block (chat_timeline_started_card.tsx) are each one of
 * these -- the same kind of thing wearing different content, so a third
 * attachment later needs nothing new here.
 */
export function MessageAttachment({children}: {children: ReactNode}) {
  return <div className={MESSAGE_ATTACHMENT_CLASSES}>{children}</div>;
}

// Props for AssistantMessage, named at module level per the destructured
// prop signature otherwise pushing the component past the line cap.
export interface AssistantMessageProps {
  /** The turn's own reply text, rendered as markdown like any other. */
  content: string;
  /** Shows the quiet fallback-authored notice above the content. */
  fallback?: boolean;
  /** The turn's chain of thought, disclosed above the content. Omitted by
   * the plan and started-session cards, whose reasoning is disclosed as a
   * separate timeline item above the whole turn instead (see
   * chat_workspace_timeline.tsx) -- passing it here as well would show it
   * twice. */
  reasoning?: string;
  /**
   * Makes the row an aria-labelled `<section>` (an accessible landmark)
   * instead of a plain `<div>`. A plain reply carries none; a turn built
   * around an attachment names what the attachment is.
   */
  ariaLabel?: string;
  /** The inline attachment this turn carries, if any -- see
   * {@link MessageAttachment}. */
  attachment?: ReactNode;
  /** The retry/copy/download row shown under the turn. */
  actions: MessageAction[];
  /**
   * Marks this row as the scroll anchor for the timeline item it renders,
   * tagging it with {@link TIMELINE_ANCHOR_ATTRIBUTE} so the auto-scroll can
   * find the turn's own top edge in the DOM (see chat_workspace_scroll.ts).
   */
  anchorId?: string;
}

/**
 * Attribute naming the timeline item a row belongs to, so the auto-scroll can
 * bring that turn's top edge into view instead of guessing at a scroll
 * offset. Read by chat_workspace_scroll.ts; written by AssistantMessage's
 * `anchorId`.
 */
export const TIMELINE_ANCHOR_ATTRIBUTE = 'data-timeline-anchor';

/**
 * Renders one assistant turn: markdown-rendered reply text, an optional
 * inline attachment carried in the turn's own flow, and the action row
 * below it -- all inside the same row/bubble wrapper a plain assistant
 * reply uses (see ChatBubble). This is what makes the research-plan turn
 * and the started-session turn read as ordinary assistant messages that
 * happen to carry an attachment, rather than as bespoke cards with their
 * own spacing and markdown rules.
 */
export function AssistantMessage({
  content,
  fallback,
  reasoning,
  ariaLabel,
  attachment,
  actions,
  anchorId,
}: AssistantMessageProps) {
  const Row: 'section' | 'div' = ariaLabel ? 'section' : 'div';
  return (
    <Row
      className={CHAT_BUBBLE_ROW_CLASSES}
      aria-label={ariaLabel}
      {...{[TIMELINE_ANCHOR_ATTRIBUTE]: anchorId}}
    >
      <div className="min-w-0">
        {fallback && <FallbackTurnNotice />}
        <ThoughtsDisclosure reasoning={reasoning} />
        <div className={MODEL_BUBBLE_CLASSES}>
          <MarkdownMessage
            content={content}
            className={MODEL_BUBBLE_TEXT_CLASSES}
          />
          {attachment}
        </div>
      </div>
      <MessageActionRow actions={actions} />
    </Row>
  );
}

// Props for ChatBubble, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
export interface ChatBubbleProps {
  message: ChatEntry;
  onSubmitEdit: (content: string) => void;
  onCopyRequest: () => void;
  onRetry: () => void;
  /**
   * Whether this message can be edited or retried at all. False for bubbles
   * with no durable turn behind them, and while the Agent is mid-turn or the
   * conversation has already been committed to a run.
   */
  revisable: boolean;
}

// The user request bubble: right-aligned, filled, collapsible past four
// lines, with the floating edit/copy row positioned against the bubble's
// real (shrink-to-fit) width. Wrapping the bubble and its actions in a
// w-fit box gives that floating row the context it needs; without it the
// row anchors to the full-width column and strands itself far to the left
// of a short prompt.
function UserBubble({
  message,
  bubbleText,
  onEdit,
  onCopyRequest,
}: {
  message: ChatEntry;
  bubbleText: ReturnType<typeof useCollapsibleBubbleText>;
  onEdit: (() => void) | null;
  onCopyRequest: () => void;
}) {
  return (
    <div className={CHAT_BUBBLE_USER_ROW_CLASSES}>
      <div className="relative w-fit">
        <div className="min-w-0">
          <ThoughtsDisclosure reasoning={message.reasoning} />
          <BubbleText
            bubbleClassName={USER_BUBBLE_CLASSES}
            content={message.content}
            {...bubbleText}
          />
        </div>
        <MessageActionRow
          align="end"
          actions={requestActions(onEdit, onCopyRequest)}
        />
      </div>
    </div>
  );
}

/**
 * Renders one chat-timeline message: a user request bubble (right-aligned,
 * filled, collapsible past four lines with an edit/copy action row) or an
 * assistant response (AssistantMessage, with a retry/copy/download action
 * row). Used as the per-message node inside ChatWorkspace's timeline.
 *
 * Editing is owned here rather than by the workspace because a prompt is
 * revised in place: the bubble swaps itself for an editor, so which message
 * is being changed is never in question. Editing only ever applies to a
 * user request (UserBubble is the only side offering an Edit action).
 */
export function ChatBubble(props: ChatBubbleProps) {
  const {message, onSubmitEdit, onCopyRequest, onRetry, revisable} = props;
  const isUser = message.role === 'user';
  const [editing, setEditing] = useState(false);
  const bubbleText = useCollapsibleBubbleText(isUser, message.content);

  if (editing) {
    return (
      <div className={CHAT_BUBBLE_USER_ROW_CLASSES}>
        <BubbleEditor
          initial={message.content}
          onCancel={() => setEditing(false)}
          onSubmit={content => {
            setEditing(false);
            onSubmitEdit(content);
          }}
        />
      </div>
    );
  }

  if (!isUser) {
    return (
      <AssistantMessage
        content={message.content}
        fallback={message.fallback}
        reasoning={message.reasoning}
        actions={responseActions(
          revisable ? onRetry : null,
          message.content,
          'co-scientist-response.md',
        )}
      />
    );
  }

  return (
    <UserBubble
      message={message}
      bubbleText={bubbleText}
      onEdit={revisable ? () => setEditing(true) : null}
      onCopyRequest={onCopyRequest}
    />
  );
}
