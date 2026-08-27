import {Fragment, useState} from 'react';
import {act, render} from '@testing-library/react';
import {beforeEach, expect, test, vi} from 'vitest';
import {useChatTimelineScroll} from './chat_workspace_scroll';
import {
  CONFIRMED_SPEC_ITEM_ID,
  DRAFT_SPEC_ITEM_ID,
  type TimelineItem,
} from './chat_workspace_timeline';
import {
  type StartedSession,
  TIMELINE_ANCHOR_ATTRIBUTE,
} from './chat_timeline_cards';

// jsdom gives every element a zero height, which would read as "already at
// the bottom" whatever scrollTop says. These are the metrics of a scroller
// holding 1000px of content in a 400px window.
const CONTENT_HEIGHT = 1000;
const WINDOW_HEIGHT = 400;
const BOTTOM = CONTENT_HEIGHT - WINDOW_HEIGHT;

function makeItems(count: number): TimelineItem[] {
  return Array.from({length: count}, (_, index) => ({
    id: `item-${index}`,
    at: index,
    order: index,
    node: null,
  }));
}

// Mounts the hook on a real element with fixed scroll metrics, leaves the
// reader at `startAt`, and returns the element plus a way to append an item
// the way a streaming turn does.
function renderScroller(startAt: number) {
  let grow: (() => void) | undefined;
  function Harness() {
    const [items, setItems] = useState(() => makeItems(1));
    grow = () => setItems(makeItems(2));
    const ref = useChatTimelineScroll(items, null);
    return <div data-testid="scroller" ref={ref} />;
  }
  const {getByTestId} = render(<Harness />);
  const scroller = getByTestId('scroller');
  Object.defineProperty(scroller, 'scrollHeight', {value: CONTENT_HEIGHT});
  Object.defineProperty(scroller, 'clientHeight', {value: WINDOW_HEIGHT});
  scroller.scrollTop = startAt;
  return {scroller, grow: () => act(() => grow?.())};
}

beforeEach(() => {
  vi.useFakeTimers();
});

test('keeps following the newest content when the reader is at the bottom', () => {
  const {scroller, grow} = renderScroller(BOTTOM);

  grow();
  act(() => void vi.runAllTimers());

  // Driven past the bottom deliberately; the browser clamps, jsdom does not.
  expect(scroller.scrollTop).toBe(CONTENT_HEIGHT);
});

test('leaves the reader where they scrolled to', () => {
  // A streaming turn appends on every token, so an auto-scroll that ignores
  // where the reader is drags them back down several times a second and
  // reading back over the reply is impossible until the turn ends.
  const {scroller, grow} = renderScroller(120);

  grow();
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(120);
});

// Mounts the hook over a started session whose card grows in place, the way
// the Agent's start announcement streams into it. The card is one item with a
// fixed id and timestamp throughout; only its `revision` moves.
function renderAnnouncingScroller(startAt: number) {
  let grow: (() => void) | undefined;
  function Harness() {
    const [intro, setIntro] = useState('');
    grow = () => setIntro(current => current + 'more');
    const session: StartedSession = {
      id: 'run-1',
      title: 'A session',
      at: 1,
      intro,
      announcing: true,
    };
    const items: TimelineItem[] = [
      {
        id: 'started-session-run-1',
        at: 1,
        order: 60,
        node: null,
        revision: intro.length,
      },
    ];
    const ref = useChatTimelineScroll(items, session);
    return <div data-testid="scroller" ref={ref} />;
  }
  const {getByTestId} = render(<Harness />);
  const scroller = getByTestId('scroller');
  Object.defineProperty(scroller, 'scrollHeight', {value: CONTENT_HEIGHT});
  Object.defineProperty(scroller, 'clientHeight', {value: WINDOW_HEIGHT});
  // The card arriving jumps the view to the bottom by design; flush that
  // before placing the reader, so what these tests measure is what the
  // *announcement* does afterwards.
  act(() => void vi.runAllTimers());
  scroller.scrollTop = startAt;
  return {scroller, grow: () => act(() => grow?.())};
}

test('follows the start announcement as it is written', () => {
  const {scroller, grow} = renderAnnouncingScroller(BOTTOM);

  grow();
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(CONTENT_HEIGHT);
});

test('leaves a reader who scrolled up during the announcement alone', () => {
  // The card is already on screen when its lead-in starts filling, so the
  // reader can be anywhere in the conversation while it does. The
  // session-started jump must not re-fire per fragment and drag them down.
  const {scroller, grow} = renderAnnouncingScroller(120);

  grow();
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(120);
});

// Mounts the hook over a conversation the plan card lands at the end of, with
// the card's row carrying the anchor attribute the real card renders. The
// rects are faked because jsdom measures everything as zero: the card's row
// sits 300px below the scroller's own top edge on screen.
const ANCHOR_ON_SCREEN_OFFSET = 300;
const SCROLLER_SCREEN_TOP = 50;

function renderPlanScroller(startAt: number, withAnchor = true) {
  let arrive: (() => void) | undefined;
  function Harness() {
    const [planned, setPlanned] = useState(false);
    arrive = () => setPlanned(true);
    const items: TimelineItem[] = makeItems(1);
    if (planned) {
      items.push({
        id: DRAFT_SPEC_ITEM_ID,
        at: 99,
        order: 50,
        node: (
          <div
            data-testid="plan-card"
            {...(withAnchor
              ? {[TIMELINE_ANCHOR_ATTRIBUTE]: DRAFT_SPEC_ITEM_ID}
              : {})}
          />
        ),
      });
    }
    const ref = useChatTimelineScroll(items, null);
    return (
      <div data-testid="scroller" ref={ref}>
        {items.map(item => (
          <Fragment key={item.id}>{item.node}</Fragment>
        ))}
      </div>
    );
  }
  const {getByTestId} = render(<Harness />);
  const scroller = getByTestId('scroller');
  Object.defineProperty(scroller, 'scrollHeight', {value: CONTENT_HEIGHT});
  Object.defineProperty(scroller, 'clientHeight', {value: WINDOW_HEIGHT});
  scroller.getBoundingClientRect = () =>
    ({top: SCROLLER_SCREEN_TOP}) as DOMRect;
  scroller.scrollTop = startAt;
  return {
    scroller,
    arrive: () => {
      act(() => arrive?.());
      const card = getByTestId('plan-card');
      card.getBoundingClientRect = () =>
        ({top: SCROLLER_SCREEN_TOP + ANCHOR_ON_SCREEN_OFFSET}) as DOMRect;
      act(() => void vi.runAllTimers());
    },
  };
}

test('opens the arriving plan turn at its own top, not the conversation top', () => {
  // scrollTop = 0 is the top of the whole conversation: the reader landed
  // back on their opening message the moment the plan was produced.
  const {scroller, arrive} = renderPlanScroller(600);

  arrive();

  expect(scroller.scrollTop).toBe(600 + ANCHOR_ON_SCREEN_OFFSET - 20);
});

test('falls back to the bottom when the plan turn cannot be located', () => {
  const {scroller, arrive} = renderPlanScroller(600, false);

  arrive();

  expect(scroller.scrollTop).toBe(CONTENT_HEIGHT);
});

test('leaves a scrolled-up reader alone when the plan is confirmed', () => {
  // Clicking Start research swaps the draft card for the confirmed one, which
  // is then the timeline's last item for the whole create+start round trip.
  // Treating that swap as an arrival is what jumped the view a second time,
  // and anchoring it now would find no draft card and drag the reader to the
  // bottom instead -- a quieter version of the same bug.
  let confirm: (() => void) | undefined;
  function Harness() {
    const [confirmed, setConfirmed] = useState(false);
    confirm = () => setConfirmed(true);
    const items: TimelineItem[] = [
      ...makeItems(1),
      {
        id: confirmed ? CONFIRMED_SPEC_ITEM_ID : DRAFT_SPEC_ITEM_ID,
        at: 99,
        order: 50,
        node: null,
      },
    ];
    const ref = useChatTimelineScroll(items, null);
    return <div data-testid="scroller" ref={ref} />;
  }
  const {getByTestId} = render(<Harness />);
  const scroller = getByTestId('scroller');
  Object.defineProperty(scroller, 'scrollHeight', {value: CONTENT_HEIGHT});
  Object.defineProperty(scroller, 'clientHeight', {value: WINDOW_HEIGHT});
  // Flush the draft card's own arrival before placing the reader.
  act(() => void vi.runAllTimers());
  scroller.scrollTop = 120;

  act(() => confirm?.());
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(120);
});
