import {type ReactNode} from 'react';
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

/**
 * One rendered chat-timeline message (either the user's or the
 * assistant's).
 */
export interface ChatEntry {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: number;
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
  onEdit: () => void;
  onCopyRequest: () => void;
  onRetry: () => void;
}

/**
 * Renders one chat-timeline message: a user request bubble (right-aligned,
 * filled, collapsible past four lines with an edit/copy action row) or an
 * assistant response (left-aligned, unstyled, with a retry/copy/download
 * action row). Used as the per-message node inside ChatWorkspace's timeline.
 */
export function ChatBubble(props: ChatBubbleProps) {
  const {message, onEdit, onCopyRequest, onRetry} = props;
  const isUser = message.role === 'user';
  const bubbleText = useCollapsibleBubbleText(isUser, message.content);
  const {row: rowClassName, bubble: bubbleClassName} =
    chatBubbleClassNames(isUser);

  return (
    <BubbleRow
      isUser={isUser}
      rowClassName={rowClassName}
      bubbleNode={
        <BubbleText
          isUser={isUser}
          bubbleClassName={bubbleClassName}
          content={message.content}
          {...bubbleText}
        />
      }
      actionsNode={
        <ChatBubbleActions
          isUser={isUser}
          message={message}
          onEdit={onEdit}
          onCopyRequest={onCopyRequest}
          onRetry={onRetry}
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
  onEdit: () => void;
  onCopyRequest: () => void;
  onRetry: () => void;
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
