import {
  useState,
  type ReactNode,
  useEffect,
  useRef,
  type KeyboardEvent,
  type CSSProperties,
  type Dispatch,
  type RefObject,
  type SetStateAction,
  type TransitionEvent,
  useLayoutEffect,
} from 'react';
import type {QaSource} from '@/api/runs';
import {MarkdownMessage} from '@/components/markdown_message';
import {
  MessageActionRow,
  requestActions,
  responseActions,
  type MessageAction,
} from './chat_timeline_message_actions';
import {ThoughtsDisclosure} from './chat_timeline_thoughts';
import {Icon} from '@/components/icon';
import {tooltipClassNames} from '../tooltip';

const CHAT_BUBBLE_USER_ROW_CLASSES =
  'reference-bubble-row user group/user relative flex flex-col items-end justify-end gap-[0.35rem]';

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
   * sources (see `runs.ts::askRunQuestion`'s `onSources` sink). Persisted
   * on the entry so a reload keeps it, but nothing renders it yet -- there
   * is no citation-chip surface designed for the chat timeline, and this
   * codebase's existing reference lists (run_detail_learning.tsx)
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
 * started-session block (chat_timeline_run_spec_card.tsx) are each one of
 * these -- the same kind of thing wearing different content, so a third
 * attachment later needs nothing new here.
 */
export function MessageAttachment({children}: {children: ReactNode}) {
  return (
    <div className="reference-message-attachment mt-[0.7rem] grid gap-[1.15rem]">
      {children}
    </div>
  );
}

// Props for AssistantMessage, named at module level per the destructured
// prop signature otherwise pushing the component past the line cap.
export interface AssistantMessageProps {
  /** The turn's own reply text, rendered as markdown like any other. */
  content: string;
  /** Shows the quiet fallback-authored notice above the content. */
  fallback?: boolean;
  /**
   * The turn's chain of thought, disclosed above the content.
   *
   * Every turn discloses its reasoning here, inside its own message. It used
   * to be a timeline entry of its own for the plan and started-session
   * turns, which put the column's gap around it (so the space above a reply
   * visibly shrank the moment the turn settled into a bubble) and let it
   * move relative to the plan when the draft stage became the confirmed one.
   */
  reasoning?: string;
  /** Whether the turn producing this message is still being written; keeps
   * the disclosure counting (see {@link ThoughtsDisclosure}). */
  live?: boolean;
  /**
   * Whether this message *is* the reply as it streams, rather than the turn
   * it resolved to. Its body is kept out of the accessibility tree: the
   * resolved message is what a screen reader should read, once, rather than
   * a partial sentence per token. The disclosure above it stays exposed --
   * it is the same one the settled turn keeps.
   */
  streaming?: boolean;
  /**
   * Makes the row an aria-labelled `<section>` (an accessible landmark)
   * instead of a plain `<div>`. A plain reply carries none; a turn built
   * around an attachment names what the attachment is.
   */
  ariaLabel?: string;
  /** The inline attachment this turn carries, if any -- see
   * {@link MessageAttachment}. */
  attachment?: ReactNode;
  /** The retry/copy/download row shown under the turn. Absent while the turn
   * is still being written: there is nothing settled to copy or retry yet. */
  actions?: MessageAction[];
  /**
   * Marks this row as the scroll anchor for the timeline item it renders,
   * tagging it with {@link TIMELINE_ANCHOR_ATTRIBUTE} so the auto-scroll can
   * find the turn's own top edge in the DOM (see chat_workspace.tsx).
   */
  anchorId?: string;
}

/**
 * Attribute naming the timeline item a row belongs to, so the auto-scroll can
 * bring that turn's top edge into view instead of guessing at a scroll
 * offset. Read by chat_workspace.tsx; written by AssistantMessage's
 * `anchorId`.
 */
export const TIMELINE_ANCHOR_ATTRIBUTE = 'data-timeline-anchor';

// The turn's action row, or nothing while it is still being written: there
// is no settled response to copy, download or regenerate yet.
function TurnActions({actions}: {actions?: MessageAction[]}) {
  if (!actions?.length) return null;
  return <MessageActionRow actions={actions} />;
}

/**
 * Renders one assistant turn: its chain of thought, its markdown-rendered
 * reply text, an optional inline attachment carried in the turn's own flow,
 * and the action row below it -- all inside the same row/bubble wrapper a
 * plain assistant reply uses (see ChatBubble). This is what makes the
 * research-plan turn and the started-session turn read as ordinary assistant
 * messages that happen to carry an attachment, rather than as bespoke cards
 * with their own spacing and markdown rules.
 *
 * The four parts render in this fixed order in every state -- streaming,
 * settled, and once a run has started -- because they are one element's
 * children rather than separate timeline entries that a re-sort could
 * reshuffle.
 */
export function AssistantMessage({
  content,
  fallback,
  reasoning,
  live,
  streaming,
  ariaLabel,
  attachment,
  actions,
  anchorId,
}: AssistantMessageProps) {
  const Row: 'section' | 'div' = ariaLabel ? 'section' : 'div';
  return (
    <Row
      className="reference-bubble-row relative flex flex-col items-start justify-start gap-[0.7rem]"
      aria-label={ariaLabel}
      {...{[TIMELINE_ANCHOR_ATTRIBUTE]: anchorId}}
    >
      <div className="min-w-0">
        {fallback && <FallbackTurnNotice />}
        <ThoughtsDisclosure
          reasoning={reasoning}
          live={live}
          answering={Boolean(live && content)}
        />
        <div
          className="reference-model-bubble max-w-[50.75rem] text-base leading-[1.45] text-cosci-fg"
          aria-hidden={streaming}
        >
          <MarkdownMessage
            content={content}
            className="reference-model-bubble-text min-w-0 break-words"
          />
          {attachment}
        </div>
      </div>
      <TurnActions actions={actions} />
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
            bubbleClassName="reference-user-bubble flex max-w-[31rem] items-start gap-4 rounded-tl-[26px] rounded-tr-[4px] rounded-br-[26px] rounded-bl-[26px] bg-cosci-user-bubble-bg py-3 pr-[0.9rem] pl-4 text-base leading-[1.45] text-cosci-fg"
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

// The user bubble's own shape (radii, fill, padding) so the prompt is edited
// where it sits -- but stacking rather than a flex row, and wider, because it
// is being written in rather than read. Spelled out instead of composed from
// USER_BUBBLE_CLASSES: that constant carries `flex`, and whether a `block`
// appended after it wins depends on Tailwind's output order, not the string's.
const EDITOR_BUBBLE_CLASSES =
  'reference-user-bubble-editor block w-[36rem] max-w-full ' +
  'rounded-tl-[26px] rounded-tr-[4px] rounded-br-[26px] rounded-bl-[26px] ' +
  'bg-cosci-user-bubble-bg px-4 py-3 text-base leading-[1.45] text-cosci-fg';

const EDITOR_TEXTAREA_CLASSES =
  'block w-full resize-none border-0 bg-transparent p-0 text-base ' +
  'leading-[1.45] text-cosci-fg outline-none';

const EDITOR_ACTIONS_CLASSES = 'mt-3 flex justify-end gap-2';

// Compact against the plan card's buttons: this row sits inside a message,
// not under a document.
const EDITOR_BUTTON_CLASSES =
  'min-h-[2.1rem] cursor-pointer rounded-full border px-4 text-sm font-medium';

const EDITOR_CANCEL_CLASSES =
  `${EDITOR_BUTTON_CLASSES} border-cosci-btn-secondary-border ` +
  'bg-transparent text-cosci-btn-secondary-fg ' +
  'hover:bg-cosci-btn-secondary-hover-bg';

const EDITOR_SEND_CLASSES =
  `${EDITOR_BUTTON_CLASSES} border-cosci-btn-primary-bg ` +
  'bg-cosci-btn-primary-bg text-cosci-btn-primary-fg ' +
  'hover:bg-cosci-btn-primary-hover disabled:cursor-default ' +
  'disabled:border-cosci-btn-disabled-border ' +
  'disabled:bg-cosci-btn-disabled-bg disabled:text-cosci-btn-disabled-fg';

// Grows the textarea to its content so a long prompt is editable whole,
// rather than through a three-line porthole.
function fitToContent(node: HTMLTextAreaElement | null): void {
  if (!node) return;
  node.style.height = 'auto';
  node.style.height = `${node.scrollHeight}px`;
}

/**
 * Edits one already-sent prompt in place.
 *
 * The prompt is revised where it stands rather than being loaded back into
 * the composer: the composer's job is the next thing to say, so putting an
 * old message there loses which message is being changed, and sending it
 * appends a second prompt instead of correcting the first. Submitting here
 * replaces the turn and everything the Agent derived from it.
 *
 * @param initial The prompt's current text.
 * @param onCancel Leaves the prompt as it was.
 * @param onSubmit Receives the revised text; only called when it changed.
 */
export function BubbleEditor({
  initial,
  onCancel,
  onSubmit,
}: {
  initial: string;
  onCancel: () => void;
  onSubmit: (content: string) => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState(initial);
  const changed = value.trim() !== '' && value.trim() !== initial.trim();

  // Opens focused with the caret at the end, sized to the prompt: editing
  // starts from a click on this exact message, so it should be ready to type
  // into without a second one.
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    fitToContent(node);
    node.focus();
    node.setSelectionRange(node.value.length, node.value.length);
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onCancel();
      return;
    }
    // Enter sends, Shift+Enter breaks the line -- the composer's contract,
    // since this is the same act of sending a prompt.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (changed) onSubmit(value);
    }
  }

  return (
    <div className={EDITOR_BUBBLE_CLASSES}>
      <textarea
        ref={ref}
        rows={1}
        aria-label="Edit prompt"
        className={EDITOR_TEXTAREA_CLASSES}
        value={value}
        onChange={event => {
          setValue(event.currentTarget.value);
          fitToContent(event.currentTarget);
        }}
        onKeyDown={handleKeyDown}
      />
      <div className={EDITOR_ACTIONS_CLASSES}>
        {/* Labelled past their visible text because a plan card's Cancel and
            the composer's Send sit on the same page. */}
        <button
          type="button"
          aria-label="Cancel edit"
          className={EDITOR_CANCEL_CLASSES}
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          aria-label="Send edited prompt"
          className={EDITOR_SEND_CLASSES}
          disabled={!changed}
          onClick={() => onSubmit(value)}
        >
          Send
        </button>
      </div>
    </div>
  );
}

const COLLAPSED_LINE_COUNT = 4;

/**
 * Measures a request bubble's collapsed (four-line) and full natural heights.
 *
 * The clamp and any inline max-height are stripped for the read so scrollHeight
 * reports the true untruncated height, then restored.
 *
 * @param element The bubble text element to measure.
 * @returns The collapsed and full pixel heights.
 */
function measureBubbleHeights(element: HTMLSpanElement) {
  const styles = window.getComputedStyle(element);
  const fontSize = Number.parseFloat(styles.fontSize) || 16;
  const lineHeight =
    Number.parseFloat(styles.lineHeight) || Math.round(fontSize * 1.45);
  const collapsed = Math.round(lineHeight * COLLAPSED_LINE_COUNT);
  const previousMaxHeight = element.style.maxHeight;
  const previousClamp = element.style.getPropertyValue('-webkit-line-clamp');
  const previousDisplay = element.style.display;
  const previousWhiteSpace = element.style.whiteSpace;
  element.style.maxHeight = 'none';
  element.style.setProperty('-webkit-line-clamp', 'unset');
  element.style.display = 'block';
  // Measure against the expanded state's wrapping so the open height is exact.
  element.style.whiteSpace = 'pre-wrap';
  const full = element.scrollHeight;
  element.style.maxHeight = previousMaxHeight;
  element.style.setProperty('-webkit-line-clamp', previousClamp);
  element.style.display = previousDisplay;
  element.style.whiteSpace = previousWhiteSpace;
  return {collapsed, full};
}

/**
 * Reports whether the user prefers reduced motion, so expand/collapse can snap
 * instead of animating.
 *
 * @returns True when the reduced-motion media query matches.
 */
function prefersReducedMotion() {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

// Pure: whether a bubble's full height overflows its collapsed (four-line)
// height enough to need the collapse/expand affordance at all. The +2 slop
// absorbs sub-pixel rounding in the measured heights.
function exceedsCollapsedHeight(heights: {
  collapsed: number;
  full: number;
}): boolean {
  return heights.full > heights.collapsed + 2;
}

// Pure: the collapsible text span's className for the current collapse/
// expand state. Collapsible bubbles pick the clamp/ellipsis classes while
// clamped and not expanded, otherwise the open (pre-wrap, no clamp) classes;
// non-collapsible bubbles get the plain (assistant) text classes.
function collapsibleTextClassName(
  collapsible: boolean,
  clamped: boolean,
  expanded: boolean,
): string {
  if (!collapsible)
    return 'reference-user-bubble-text min-w-0 break-words whitespace-pre-wrap';
  const stateClasses =
    clamped && !expanded
      ? 'block whitespace-normal'
      : 'block whitespace-pre-wrap';
  return `${'reference-user-bubble-text min-w-0 break-words overflow-hidden transition-[max-height] duration-300 ease-out motion-reduce:transition-none'} ${stateClasses}`;
}

// Pure: the collapsible text span's inline max-height style, which drives
// the animated transition. Collapsed height while closed, the measured full
// height while opening, and no cap at all once `settled` so a later window
// resize can't leave the bubble clipped. Undefined for non-collapsible
// bubbles, which carry no inline max-height at all.
function collapsibleTextStyle(
  collapsible: boolean,
  expanded: boolean,
  settled: boolean,
  heights: {collapsed: number; full: number},
): CSSProperties | undefined {
  if (!collapsible) return undefined;
  return {
    maxHeight: expanded
      ? settled
        ? undefined
        : `${heights.full}px`
      : `${heights.collapsed}px`,
  };
}

// A bubble's collapsed (four-line) and full natural pixel heights, as
// measured by measureBubbleHeights.
interface BubbleHeights {
  collapsed: number;
  full: number;
}

// The bundled state useCollapsibleBubbleText builds once per render, so
// remeasureBubbleOnChange/toggleBubbleExpanded/collapsibleBubbleTextResult
// below can each take a single argument instead of repeating every field.
interface CollapsibleBubbleTextState {
  textRef: RefObject<HTMLSpanElement | null>;
  isUser: boolean;
  canCollapse: boolean;
  expanded: boolean;
  clamped: boolean;
  settled: boolean;
  heights: BubbleHeights;
  setCanCollapse: Dispatch<SetStateAction<boolean>>;
  setExpanded: Dispatch<SetStateAction<boolean>>;
  setClamped: Dispatch<SetStateAction<boolean>>;
  setSettled: Dispatch<SetStateAction<boolean>>;
  setHeights: Dispatch<SetStateAction<BubbleHeights>>;
}

// Re-measures on content/role change and resets to collapsed, so a reused
// node doesn't inherit a stale expanded/settled state. Body of the
// useLayoutEffect in useCollapsibleBubbleText below.
function remeasureBubbleOnChange(state: CollapsibleBubbleTextState): void {
  const {isUser, textRef, setCanCollapse, setHeights, setExpanded} = state;
  const {setSettled, setClamped} = state;
  if (!isUser || !textRef.current) {
    setCanCollapse(false);
    return;
  }
  const measured = measureBubbleHeights(textRef.current);
  const exceeds = exceedsCollapsedHeight(measured);
  setHeights(measured);
  setCanCollapse(exceeds);
  setExpanded(false);
  setSettled(false);
  setClamped(exceeds);
}

// Flips collapsed/expanded, re-measuring first in case metrics (e.g. a font
// load) shifted since the last measurement.
function toggleBubbleExpanded(
  state: Pick<
    CollapsibleBubbleTextState,
    | 'textRef'
    | 'expanded'
    | 'setHeights'
    | 'setExpanded'
    | 'setClamped'
    | 'setSettled'
  >,
): void {
  const {textRef, expanded, setHeights, setExpanded, setClamped, setSettled} =
    state;
  const element = textRef.current;
  if (element) setHeights(measureBubbleHeights(element));
  if (expanded) {
    // Collapse: drop the max-height cap to a concrete height, then animate
    // down next frame; the clamp returns on transition end.
    setSettled(false);
    if (prefersReducedMotion()) {
      setExpanded(false);
      setClamped(true);
    } else {
      requestAnimationFrame(() => setExpanded(false));
    }
  } else {
    // Expand: drop the clamp first so the max-height change animates.
    setClamped(false);
    if (prefersReducedMotion()) {
      setExpanded(true);
      setSettled(true);
    } else {
      requestAnimationFrame(() => setExpanded(true));
    }
  }
}

// Locks in the clamp (collapse) or drops the cap via `settled` (expand) once
// the animated max-height transition finishes.
function handleBubbleTransitionEndFor(
  expanded: boolean,
  setSettled: Dispatch<SetStateAction<boolean>>,
  setClamped: Dispatch<SetStateAction<boolean>>,
  event: TransitionEvent<HTMLSpanElement>,
): void {
  if (event.propertyName !== 'max-height') return;
  if (expanded) {
    setSettled(true);
  } else {
    setClamped(true);
  }
}

// Pure: the collapsible text span's className/style pair for the current
// collapse/expand state.
function deriveBubbleTextPresentation(
  collapsible: boolean,
  clamped: boolean,
  expanded: boolean,
  settled: boolean,
  heights: BubbleHeights,
): {bubbleTextClassName: string; bubbleTextStyle: CSSProperties | undefined} {
  return {
    bubbleTextClassName: collapsibleTextClassName(
      collapsible,
      clamped,
      expanded,
    ),
    bubbleTextStyle: collapsibleTextStyle(
      collapsible,
      expanded,
      settled,
      heights,
    ),
  };
}

// Derives useCollapsibleBubbleText's returned textRef/collapsible/expanded/
// handler bundle from its raw state, once collapsible is known.
function collapsibleBubbleTextResult(state: CollapsibleBubbleTextState) {
  const collapsible = state.isUser && state.canCollapse;
  return {
    textRef: state.textRef,
    collapsible,
    expanded: state.expanded,
    ...deriveBubbleTextPresentation(
      collapsible,
      state.clamped,
      state.expanded,
      state.settled,
      state.heights,
    ),
    toggleExpanded: () => toggleBubbleExpanded(state),
    handleBubbleTransitionEnd: (event: TransitionEvent<HTMLSpanElement>) =>
      handleBubbleTransitionEndFor(
        state.expanded,
        state.setSettled,
        state.setClamped,
        event,
      ),
  };
}

/**
 * Owns a user bubble's collapse/expand-past-four-lines behavior: measures
 * the collapsed and full heights, tracks expanded/clamped/settled state, and
 * derives the text span's className/style for the animated max-height
 * transition. A no-op for assistant bubbles (`isUser` false).
 *
 * @param isUser Whether this bubble is a user (collapsible) or assistant
 *   (never collapsible) message.
 * @param content The bubble's text content, re-measured whenever it changes.
 */
export function useCollapsibleBubbleText(isUser: boolean, content: string) {
  const textRef = useRef<HTMLSpanElement>(null);
  // Whether this bubble needs the collapse/expand affordance (user only).
  const [canCollapse, setCanCollapse] = useState(false);
  // Whether a collapsible bubble is expanded to its full height.
  const [expanded, setExpanded] = useState(false);
  // `clamped` gates the ellipsis; `settled` drops the max-height cap once
  // fully open so a later resize can't clip it.
  const [clamped, setClamped] = useState(false);
  const [settled, setSettled] = useState(false);
  // Last-measured collapsed/full pixel heights, feeding collapsibleTextStyle.
  const [heights, setHeights] = useState<BubbleHeights>({
    collapsed: 0,
    full: 0,
  });

  // Bundled once so remeasureBubbleOnChange and collapsibleBubbleTextResult
  // below can each take a single argument.
  const state: CollapsibleBubbleTextState = {
    textRef,
    isUser,
    canCollapse,
    expanded,
    clamped,
    settled,
    heights,
    setCanCollapse,
    setExpanded,
    setClamped,
    setSettled,
    setHeights,
  };

  // Re-measures on content/role change and resets to collapsed, so a reused
  // node doesn't inherit a stale expanded/settled state.
  useLayoutEffect(() => remeasureBubbleOnChange(state), [isUser, content]);

  return collapsibleBubbleTextResult(state);
}

// Props for BubbleText below: the collapsible-text hook's full return bundle
// plus the bubbleClassName/content fields it needs to render.
export interface BubbleTextProps {
  bubbleClassName: string;
  content: string;
  textRef: RefObject<HTMLSpanElement | null>;
  collapsible: boolean;
  expanded: boolean;
  bubbleTextClassName: string;
  bubbleTextStyle: CSSProperties | undefined;
  toggleExpanded: () => void;
  handleBubbleTransitionEnd: (event: TransitionEvent<HTMLSpanElement>) => void;
}

// A user request bubble's text span, with the collapse/expand toggle
// appended when it needs one. Stays a plain text span -- it carries what
// the scientist typed, which must never be reinterpreted as markup -- and
// the collapse measurement above reads that span's own metrics, pre-wrap
// included. (An assistant reply's markdown rendering lives in
// AssistantMessage, chat_timeline_bubble.tsx -- this component only ever
// renders the user side now.)
export function BubbleText({
  bubbleClassName,
  content,
  textRef,
  collapsible,
  expanded,
  bubbleTextClassName,
  bubbleTextStyle,
  toggleExpanded,
  handleBubbleTransitionEnd,
}: BubbleTextProps) {
  return (
    <div className={bubbleClassName}>
      <span
        ref={textRef}
        className={bubbleTextClassName}
        style={bubbleTextStyle}
        onTransitionEnd={collapsible ? handleBubbleTransitionEnd : undefined}
      >
        {content}
      </span>
      {collapsible && (
        <CollapseToggleButton expanded={expanded} onToggle={toggleExpanded} />
      )}
    </div>
  );
}

// The collapse/expand-past-four-lines toggle shown under a collapsible user
// bubble's text. A pointer click drops focus afterward so the hover-revealed
// action row (edit/copy, shown via group-focus-within) doesn't stay up once
// the pointer leaves; keyboard activation (detail 0) keeps focus so those
// users can still reach the actions.
function CollapseToggleButton({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={tooltipClassNames({
        className:
          'reference-user-collapse size-8 shrink-0 grid cursor-pointer place-items-center rounded-full border-0 bg-transparent p-0 text-[1.25rem] text-cosci-muted hover:bg-cosci-user-bubble-hover hover:text-cosci-fg focus-visible:bg-cosci-user-bubble-hover focus-visible:text-cosci-fg',
        placement: 'right',
      })}
      aria-label={expanded ? 'Collapse' : 'Expand'}
      data-tooltip={expanded ? 'Collapse' : 'Expand'}
      onClick={event => {
        onToggle();
        if (event.detail > 0) event.currentTarget.blur();
      }}
    >
      <Icon
        aria-hidden="true"
        name={expanded ? 'expand_less' : 'expand_more'}
      />
    </button>
  );
}
