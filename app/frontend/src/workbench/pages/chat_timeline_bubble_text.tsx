import {
  type CSSProperties,
  type Dispatch,
  type RefObject,
  type SetStateAction,
  type TransitionEvent,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import {Icon} from '@/components/icon';
import {tooltipClassNames} from '../tooltip';
import {
  USER_BUBBLE_TEXT_CLAMP_CLASSES,
  USER_BUBBLE_TEXT_CLASSES,
  USER_BUBBLE_TEXT_COLLAPSIBLE_CLASSES,
  USER_BUBBLE_TEXT_OPEN_CLASSES,
  USER_COLLAPSE_BUTTON_CLASSES,
} from './chat_setup_classes';

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
  if (!collapsible) return USER_BUBBLE_TEXT_CLASSES;
  const stateClasses =
    clamped && !expanded
      ? USER_BUBBLE_TEXT_CLAMP_CLASSES
      : USER_BUBBLE_TEXT_OPEN_CLASSES;
  return `${USER_BUBBLE_TEXT_COLLAPSIBLE_CLASSES} ${stateClasses}`;
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
// plus the isUser/bubbleClassName/content fields it needs to render.
export interface BubbleTextProps {
  isUser: boolean;
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

// The bubble's text span, with the collapse/expand toggle appended for
// collapsible (user) bubbles.
export function BubbleText({
  isUser,
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
        ref={isUser ? textRef : undefined}
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
        className: USER_COLLAPSE_BUTTON_CLASSES,
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
