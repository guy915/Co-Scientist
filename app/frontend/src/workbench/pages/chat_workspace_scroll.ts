import {type RefObject, useEffect, useRef} from 'react';
import {type StartedSession} from './chat_timeline_cards';
import {type TimelineItem} from './chat_workspace_timeline';

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
    .map(item => `${item.id}:${item.at}`)
    .join('|');
  const latestTimelineItemId =
    timelineItems.length > 0 ? timelineItems[timelineItems.length - 1].id : '';
  // Once a run has started, always anchor to the bottom. Otherwise, a newly
  // arrived spec card (which is tall) anchors to the top so its heading is
  // visible; anything else (chat bubbles) anchors to the bottom as usual.
  const anchorMode: 'top' | 'bottom' = startedSession
    ? 'bottom'
    : latestTimelineItemId === 'draft-spec' ||
        latestTimelineItemId === 'confirmed-spec'
      ? 'top'
      : 'bottom';
  return {signature, anchorMode};
}

// Effect body for the signature-based auto-scroll below: fires whenever the
// timeline's signature changes (new item, or an item's timestamp changed),
// skipping the very first render's signature and any re-render that doesn't
// actually change the timeline. The zero-delay timeout defers until after
// layout so scrollHeight reflects the new DOM.
function syncTimelineScroll(
  scrollRef: RefObject<HTMLDivElement | null>,
  previousTimelineSignature: RefObject<string>,
  timelineSignature: string,
  timelineAnchorMode: 'top' | 'bottom',
) {
  const scroller = scrollRef.current;
  if (!scroller || previousTimelineSignature.current === timelineSignature) {
    return;
  }
  previousTimelineSignature.current = timelineSignature;
  const timeout = window.setTimeout(() => {
    scroller.scrollTop =
      timelineAnchorMode === 'top' ? 0 : scroller.scrollHeight;
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
 * @returns The ref to attach to the scrollable timeline container.
 */
export function useChatTimelineScroll(
  timelineItems: TimelineItem[],
  startedSession: StartedSession | null,
) {
  // Scrollable timeline container; scrollTop is driven imperatively below.
  const scrollRef = useRef<HTMLDivElement>(null);
  // Last timeline signature we auto-scrolled for, so the effect below only
  // fires when the timeline actually changed shape/order.
  const previousTimelineSignature = useRef('');

  const {signature: timelineSignature, anchorMode: timelineAnchorMode} =
    timelineScrollTarget(timelineItems, startedSession);

  useEffect(
    () =>
      syncTimelineScroll(
        scrollRef,
        previousTimelineSignature,
        timelineSignature,
        timelineAnchorMode,
      ),
    [timelineAnchorMode, timelineSignature],
  );

  useEffect(
    () => syncStartedSessionScroll(scrollRef, startedSession),
    [startedSession],
  );

  return scrollRef;
}
