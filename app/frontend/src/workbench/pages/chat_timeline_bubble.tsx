import {useState, type ReactNode} from 'react';
import {
  CHAT_BUBBLE_ROW_CLASSES,
  CHAT_BUBBLE_USER_ROW_CLASSES,
  MODEL_BUBBLE_CLASSES,
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

// The bubble's provenance marker: a fallback-authored assistant turn shows
// the scripted-question notice; every other turn shows nothing. Kept out of
// ChatBubble's own body so its branch does not count against the bubble.
function bubbleProvenanceNotice(message: ChatEntry) {
  if (message.role !== 'assistant' || !message.fallback) return null;
  return <FallbackTurnNotice />;
}

// The bubble row wrapper: a user bubble's edit/copy row floats to the left of
// the bubble, so it must be positioned against the bubble's real
// (shrink-to-fit) width. Wrapping the bubble and its actions in a w-fit box
// gives the absolute row that context; without it the row anchors to the
// full-width column and strands itself far to the left of a short prompt.
// Assistant bubbles keep their inline row.
function BubbleRow({
  isUser,
  rowClassName,
  bubbleNode,
  actionsNode,
}: {
  isUser: boolean;
  rowClassName: string;
  bubbleNode: ReactNode;
  actionsNode: ReactNode;
}) {
  return (
    <div className={rowClassName}>
      {isUser ? (
        <div className="relative w-fit">
          {bubbleNode}
          {actionsNode}
        </div>
      ) : (
        <>
          {bubbleNode}
          {actionsNode}
        </>
      )}
    </div>
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

/**
 * Renders one chat-timeline message: a user request bubble (right-aligned,
 * filled, collapsible past four lines with an edit/copy action row) or an
 * assistant response (left-aligned, unstyled, with a retry/copy/download
 * action row). Used as the per-message node inside ChatWorkspace's timeline.
 *
 * Editing is owned here rather than by the workspace because a prompt is
 * revised in place: the bubble swaps itself for an editor, so which message
 * is being changed is never in question.
 */
export function ChatBubble(props: ChatBubbleProps) {
  const {message, onSubmitEdit, onCopyRequest, onRetry, revisable} = props;
  const isUser = message.role === 'user';
  const [editing, setEditing] = useState(false);
  const bubbleText = useCollapsibleBubbleText(isUser, message.content);
  const {row: rowClassName, bubble: bubbleClassName} =
    chatBubbleClassNames(isUser);

  if (editing) {
    return (
      <div className={rowClassName}>
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

  return (
    <BubbleRow
      isUser={isUser}
      rowClassName={rowClassName}
      bubbleNode={
        <div className="min-w-0">
          {/* Above the answer, like the thinking it replaces: a fallback
              turn has no model and therefore no reasoning, so the notice is
              the only provenance the bubble carries. */}
          {bubbleProvenanceNotice(message)}
          {/* Above the answer, where the live trail was: the thinking came
              first, and reading it after the reply reverses the turn. */}
          <ThoughtsDisclosure reasoning={message.reasoning} />
          <BubbleText
            isUser={isUser}
            bubbleClassName={bubbleClassName}
            content={message.content}
            {...bubbleText}
          />
        </div>
      }
      actionsNode={
        <ChatBubbleActions
          isUser={isUser}
          message={message}
          onEdit={revisable ? () => setEditing(true) : null}
          onCopyRequest={onCopyRequest}
          onRetry={revisable ? onRetry : null}
        />
      }
    />
  );
}

// The row wrapper and bubble className pair for a message, keyed off whether
// it's the user's (right-aligned, filled) or the assistant's (left-aligned,
// unstyled).
function chatBubbleClassNames(isUser: boolean): {
  row: string;
  bubble: string;
} {
  return isUser
    ? {row: CHAT_BUBBLE_USER_ROW_CLASSES, bubble: USER_BUBBLE_CLASSES}
    : {row: CHAT_BUBBLE_ROW_CLASSES, bubble: MODEL_BUBBLE_CLASSES};
}

// The message action row under a chat bubble: the floating edit/copy row for
// a user request, or the retry/copy/download row for an assistant response.
function ChatBubbleActions({
  isUser,
  message,
  onEdit,
  onCopyRequest,
  onRetry,
}: {
  isUser: boolean;
  message: ChatEntry;
  onEdit: (() => void) | null;
  onCopyRequest: () => void;
  onRetry: (() => void) | null;
}) {
  if (isUser) {
    return (
      <MessageActionRow
        align="end"
        actions={requestActions(onEdit, onCopyRequest)}
      />
    );
  }
  return (
    <MessageActionRow
      actions={responseActions(
        onRetry,
        message.content,
        'co-scientist-response.md',
      )}
    />
  );
}
