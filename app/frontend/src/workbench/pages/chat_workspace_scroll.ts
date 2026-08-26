import {type RefObject, useEffect, useRef} from 'react';
import {type StartedSession} from './chat_timeline_cards';
import {
  CONFIRMED_SPEC_ITEM_ID,
  DRAFT_SPEC_ITEM_ID,
  type TimelineItem,
} from './chat_workspace_timeline';

// Cheap fingerprint of the timeline's identity/order, used to detect when it
// actually changed shape/order without deep-comparing React nodes, plus
// whether an auto-scroll should anchor to the top (a newly arrived, tall
// spec card) or bottom (everything else, and always once a session has
// started).
function timelineScrollTarget(
  timelineItems: TimelineItem[],
  startedSession: StartedSession | null,
): {signature: string; anchorMode: 'top' | 'bottom'} {
  const signature = timelineItems
    .map(item => `${item.id}:${item.at}:${item.revision ?? ''}`)
    .join('|');
  const latestTimelineItemId =
    timelineItems.length > 0 ? timelineItems[timelineItems.length - 1].id : '';
  // Once a run has started, always anchor to the bottom. Otherwise, a newly
  // arrived spec card (which is tall) anchors to the top so its heading is
  // visible; anything else (chat bubbles) anchors to the bottom as usual.
  const anchorMode: 'top' | 'bottom' = startedSession
    ? 'bottom'
    : latestTimelineItemId === DRAFT_SPEC_ITEM_ID ||
        latestTimelineItemId === CONFIRMED_SPEC_ITEM_ID
      ? 'top'
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

// Effect body for the signature-based auto-scroll below: fires whenever the
// timeline's signature changes (new item, or an item's timestamp changed),
// skipping the very first render's signature and any re-render that doesn't
// actually change the timeline. A bottom anchor only follows a reader who is
// already at the bottom; a top anchor (a tall spec card arriving) is a
// discrete event and jumps regardless. The zero-delay timeout defers until
// after layout so scrollHeight reflects the new DOM.
function syncTimelineScroll(
  refs: TimelineScrollRefs,
  timelineSignature: string,
  timelineAnchorMode: 'top' | 'bottom',
) {
  const scroller = refs.scroller.current;
  if (!scroller || refs.previousSignature.current === timelineSignature) {
    return;
  }
  refs.previousSignature.current = timelineSignature;
  if (timelineAnchorMode === 'bottom' && !isFollowingBottom(scroller)) return;
  const timeout = window.setTimeout(() => {
    scroller.scrollTop =
      timelineAnchorMode === 'top' ? 0 : scroller.scrollHeight;
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
