import {type RefObject, useEffect, useRef} from 'react';
import {
  type StartedSession,
  TIMELINE_ANCHOR_ATTRIBUTE,
} from './chat_timeline_cards';
import {DRAFT_SPEC_ITEM_ID, type TimelineItem} from './chat_workspace_timeline';

// Cheap fingerprint of the timeline's identity/order, used to detect when it
// actually changed shape/order without deep-comparing React nodes, plus
// whether an auto-scroll should bring the newly arrived plan turn's own top
// edge into view or simply follow the bottom (everything else, and always
// once a session has started).
//
// Only the *draft* plan card anchors that way, and only while no run has
// started. The confirmed card deliberately does not: it replaces the draft
// in place, so it is the same card the reader is already looking at rather
// than a new arrival -- and it becomes the timeline's last item for the
// length of the create+start round trip, which is exactly when the reader is
// waiting for the reply that follows it.
function timelineScrollTarget(
  timelineItems: TimelineItem[],
  startedSession: StartedSession | null,
): {signature: string; anchorMode: 'plan' | 'bottom'} {
  const signature = timelineItems
    .map(item => `${item.id}:${item.at}:${item.revision ?? ''}`)
    .join('|');
  const latestTimelineItemId =
    timelineItems.length > 0 ? timelineItems[timelineItems.length - 1].id : '';
  const anchorMode: 'plan' | 'bottom' =
    !startedSession && latestTimelineItemId === DRAFT_SPEC_ITEM_ID
      ? 'plan'
      : 'bottom';
  return {signature, anchorMode};
}

// How close to the bottom still counts as following along. Anything further
// up is a reader who scrolled there deliberately, and that position is
// theirs to keep: a streaming turn appends text on every token, so without
// this the timeline hauled them back down several times a second and reading
// back over the reply was impossible until the turn finished.
const FOLLOW_THRESHOLD_PX = 64;

// The two refs the scroll effects below share: the scroller itself and the
// last signature auto-scrolled for.
interface TimelineScrollRefs {
  scroller: RefObject<HTMLDivElement | null>;
  previousSignature: RefObject<string>;
}

/**
 * Whether the reader is close enough to the bottom to be following along.
 *
 * Measured here, at the moment of the scroll, rather than tracked from a
 * `scroll` listener. The listener version has a hole: the browser delivers
 * scroll events asynchronously, so a token landing in the same frame as the
 * reader's gesture still sees the stale "at the bottom" flag and hauls them
 * back down -- and once back at the bottom the flag is true again, so they
 * are stuck there. This runs after the DOM has already grown, which only
 * costs the growth itself (a line or so per fragment), well inside the
 * threshold.
 */
function isFollowingBottom(scroller: HTMLDivElement): boolean {
  const gap =
    scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
  return gap <= FOLLOW_THRESHOLD_PX;
}

// Breathing room left above an anchored turn, matching the timeline's own
// top padding (CHAT_TIMELINE_CLASSES' `pt-5`) so the turn sits where the
// first turn of a fresh conversation sits rather than flush against the
// pane's edge.
const ANCHOR_TOP_INSET_PX = 20;

/**
 * Scrolls the timeline so the given item's own top edge sits just below the
 * scroller's top edge.
 *
 * The plan turn is tall, so following the bottom would open it at its Start
 * button with the message that introduces it off screen. What it must never
 * do is scroll the *container* to zero: that is the top of the whole
 * conversation, which for anything past a couple of turns threw the reader
 * back to their opening message the moment the plan arrived.
 *
 * Falls back to the bottom when the element cannot be found, for the same
 * reason -- zero is never the answer here.
 */
function scrollItemToTop(scroller: HTMLDivElement, itemId: string): void {
  const anchor = scroller.querySelector<HTMLElement>(
    `[${TIMELINE_ANCHOR_ATTRIBUTE}="${itemId}"]`,
  );
  if (!anchor) {
    scroller.scrollTop = scroller.scrollHeight;
    return;
  }
  // The element's on-screen offset from the scroller's own top edge is how
  // far the scroller has to travel to put it there (mirrors
  // lib/smooth_scroll.ts). Assignment clamps, so an anchor near the end of a
  // short timeline simply lands as low as the content allows.
  const offset =
    anchor.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
  scroller.scrollTop += offset - ANCHOR_TOP_INSET_PX;
}

// Effect body for the signature-based auto-scroll below: fires whenever the
// timeline's signature changes (new item, or an item's timestamp changed),
// skipping the very first render's signature and any re-render that doesn't
// actually change the timeline. A bottom anchor only follows a reader who is
// already at the bottom; the plan anchor (a tall card arriving) is a discrete
// event and moves the view regardless. The zero-delay timeout defers until
// after layout, so both scrollHeight and the anchor's rect reflect the new
// DOM.
function syncTimelineScroll(
  refs: TimelineScrollRefs,
  timelineSignature: string,
  timelineAnchorMode: 'plan' | 'bottom',
) {
  const scroller = refs.scroller.current;
  if (!scroller || refs.previousSignature.current === timelineSignature) {
    return;
  }
  refs.previousSignature.current = timelineSignature;
  if (timelineAnchorMode === 'bottom' && !isFollowingBottom(scroller)) return;
  const timeout = window.setTimeout(() => {
    if (timelineAnchorMode === 'plan') {
      scrollItemToTop(scroller, DRAFT_SPEC_ITEM_ID);
      return;
    }
    scroller.scrollTop = scroller.scrollHeight;
  }, 0);
  return () => window.clearTimeout(timeout);
}

// Effect body for the scroll that follows sending a turn. Sending is an
// explicit act, so it re-attaches the view wherever the reader had scrolled
// to -- otherwise a follow-up typed while reading back would appear off
// screen with nothing seeming to happen.
function syncSentTurnScroll(
  refs: TimelineScrollRefs,
  isAwaitingAgent: boolean,
) {
  const scroller = refs.scroller.current;
  if (!isAwaitingAgent || !scroller) return;
  const timeout = window.setTimeout(() => {
    scroller.scrollTop = scroller.scrollHeight;
  }, 0);
  return () => window.clearTimeout(timeout);
}

// Effect body for the belt-and-suspenders scroll-to-bottom below: fires
// specifically when a session starts, independent of the signature-based
// effect above, since the started-card arriving can coincide with other
// timeline changes.
function syncStartedSessionScroll(
  scrollRef: RefObject<HTMLDivElement | null>,
  startedSession: StartedSession | null,
) {
  const scroller = scrollRef.current;
  if (!startedSession || !scroller) {
    return;
  }
  const timeout = window.setTimeout(() => {
    scroller.scrollTop = scroller.scrollHeight;
  }, 0);
  return () => window.clearTimeout(timeout);
}

/**
 * Owns the timeline's auto-scroll behavior: derives a scroll signature and
 * anchor mode from the current items (see timelineScrollTarget), then scrolls
 * the returned ref accordingly whenever the timeline changes or a session
 * starts (see syncTimelineScroll and syncStartedSessionScroll).
 *
 * @param timelineItems The current, already-sorted timeline items.
 * @param startedSession The started session, if any (always anchors bottom).
 * @param isAwaitingAgent Whether a turn is in flight; its rising edge is the
 *   reader's own send, which re-attaches the view to the bottom.
 * @returns The ref to attach to the scrollable timeline container.
 */
export function useChatTimelineScroll(
  timelineItems: TimelineItem[],
  startedSession: StartedSession | null,
  isAwaitingAgent = false,
) {
  // Scrollable timeline container; scrollTop is driven imperatively below.
  const scrollRef = useRef<HTMLDivElement>(null);
  // Last timeline signature we auto-scrolled for, so the effect below only
  // fires when the timeline actually changed shape/order.
  const previousTimelineSignature = useRef('');
  const refs: TimelineScrollRefs = {
    scroller: scrollRef,
    previousSignature: previousTimelineSignature,
  };

  const {signature: timelineSignature, anchorMode: timelineAnchorMode} =
    timelineScrollTarget(timelineItems, startedSession);

  useEffect(
    () => syncTimelineScroll(refs, timelineSignature, timelineAnchorMode),
    [timelineAnchorMode, timelineSignature],
  );

  useEffect(() => syncSentTurnScroll(refs, isAwaitingAgent), [isAwaitingAgent]);

  // Keyed on the session's id, not the session object: the Agent's start
  // announcement streams into that object fragment by fragment, and this
  // scroll ignores where the reader is by design -- re-running it per
  // fragment would haul a reader who scrolled up back down on every token,
  // the exact behaviour isFollowingBottom exists to prevent. The growth
  // itself reaches the follow-aware effect above through the item's
  // `revision`.
  useEffect(
    () => syncStartedSessionScroll(scrollRef, startedSession),
    [startedSession?.id],
  );

  return scrollRef;
}
