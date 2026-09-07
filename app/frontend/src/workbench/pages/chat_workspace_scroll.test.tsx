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

// Mounts the hook empty (the real timing: a fresh mount/reopen renders
// before rehydration has fetched anything), then lets the test populate it
// the way rehydration does. Dimensions are defined after render, like every
// other harness -- jsdom measures a freshly mounted element as zero either
// way, so what actually matters here is that scrollTop is never touched
// before `populate` runs: a real browser leaves it at 0 too.
function renderFreshScroller(conversationId?: string) {
  let populate: ((items: TimelineItem[]) => void) | undefined;
  let setConversation: ((id: string | undefined) => void) | undefined;
  function Harness() {
    const [items, setItems] = useState<TimelineItem[]>([]);
    const [id, setId] = useState(conversationId);
    populate = setItems;
    setConversation = setId;
    const ref = useChatTimelineScroll(items, null, false, id);
    return <div data-testid="scroller" ref={ref} />;
  }
  const {getByTestId} = render(<Harness />);
  const scroller = getByTestId('scroller');
  Object.defineProperty(scroller, 'scrollHeight', {value: CONTENT_HEIGHT});
  Object.defineProperty(scroller, 'clientHeight', {value: WINDOW_HEIGHT});
  return {
    scroller,
    populate: (items: TimelineItem[]) => act(() => populate?.(items)),
    switchConversation: (id: string, items: TimelineItem[]) =>
      act(() => {
        setConversation?.(id);
        populate?.(items);
      }),
  };
}

test('lands at the bottom the first time a fresh mount gets real content', () => {
  // Reopening a chat -- from the results tab or straight from the sidebar --
  // mounts the hook before the transcript has loaded. The reader must never
  // be left at scrollTop 0 once it arrives.
  const {scroller, populate} = renderFreshScroller();

  populate(makeItems(20));
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(CONTENT_HEIGHT);
});

test('leaves a reader who scrolled up alone once the initial load has settled', () => {
  const {scroller, populate} = renderFreshScroller();
  populate(makeItems(20));
  act(() => void vi.runAllTimers());

  // The initial land-at-bottom already happened; the reader now scrolls up
  // to read back, and a further streamed fragment must not haul them down.
  scroller.scrollTop = 120;
  populate(makeItems(21));
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(120);
});

test('switching to a different chat without remounting still lands at the bottom', () => {
  // ChatWorkspace does not remount for a sidebar switch between two already-
  // loaded chats ("/chats/:id" is a param change on the same route), and
  // rehydration replaces the whole message log in one step rather than
  // passing through empty -- so a mount-only ref would miss this case.
  const {scroller, populate, switchConversation} =
    renderFreshScroller('chat-a');
  populate(makeItems(20));
  act(() => void vi.runAllTimers());
  scroller.scrollTop = 120;

  switchConversation('chat-b', makeItems(5));
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(CONTENT_HEIGHT);
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

function renderPlanScroller(
  startAt: number,
  withAnchor = true,
  cardHeight = 0,
) {
  let arrive: (() => void) | undefined;
  let confirm: (() => void) | undefined;
  function Harness() {
    const [planned, setPlanned] = useState(false);
    const [confirmed, setConfirmed] = useState(false);
    arrive = () => setPlanned(true);
    confirm = () => setConfirmed(true);
    const items: TimelineItem[] = makeItems(1);
    if (planned) {
      items.push({
        id: confirmed ? CONFIRMED_SPEC_ITEM_ID : DRAFT_SPEC_ITEM_ID,
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
  let contentHeight = CONTENT_HEIGHT;
  Object.defineProperty(scroller, 'scrollHeight', {get: () => contentHeight});
  Object.defineProperty(scroller, 'clientHeight', {value: WINDOW_HEIGHT});
  scroller.getBoundingClientRect = () =>
    ({top: SCROLLER_SCREEN_TOP}) as DOMRect;
  scroller.scrollTop = startAt;
  return {
    scroller,
    arrive: () => {
      contentHeight += cardHeight;
      act(() => arrive?.());
      const card = getByTestId('plan-card');
      card.getBoundingClientRect = () =>
        ({top: SCROLLER_SCREEN_TOP + ANCHOR_ON_SCREEN_OFFSET}) as DOMRect;
      act(() => void vi.runAllTimers());
    },
    confirm: () => {
      act(() => confirm?.());
      act(() => void vi.runAllTimers());
    },
    contentHeight: () => contentHeight,
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

// Mounts the hook on a scroller that behaves like a real one: scrollTop
// clamps to the bottom of the content, and the content grows by whatever a
// streamed fragment adds. The other harnesses here pin scrollHeight, which
// makes every post-scroll gap negative and so hides what happens once a
// fragment adds more than FOLLOW_THRESHOLD_PX at once.
function renderGrowingScroller() {
  let grow: ((by: number) => void) | undefined;
  function Harness() {
    const [length, setLength] = useState(0);
    grow = (by: number) => setLength(current => current + by);
    const items: TimelineItem[] = [
      {
        id: 'agent-turn-in-flight',
        at: 1,
        order: 45,
        node: null,
        revision: length,
      },
    ];
    const ref = useChatTimelineScroll(items, null);
    return <div data-testid="scroller" ref={ref} />;
  }
  const {getByTestId} = render(<Harness />);
  const scroller = getByTestId('scroller');
  let contentHeight = CONTENT_HEIGHT;
  let top = 0;
  Object.defineProperty(scroller, 'scrollHeight', {get: () => contentHeight});
  Object.defineProperty(scroller, 'clientHeight', {value: WINDOW_HEIGHT});
  Object.defineProperty(scroller, 'scrollTop', {
    get: () => top,
    set: (value: number) => {
      top = Math.max(0, Math.min(value, contentHeight - WINDOW_HEIGHT));
    },
  });
  return {
    scroller,
    grow: (by: number) => {
      contentHeight += by;
      act(() => grow?.(by));
      act(() => void vi.runAllTimers());
    },
  };
}

test('keeps following when one fragment adds more than the follow threshold', () => {
  // The gap is measured after the DOM has already grown, so a fragment
  // taller than FOLLOW_THRESHOLD_PX reads as a reader who scrolled away --
  // and since the skip leaves scrollTop where it was, every later fragment
  // reads the same way. The turn followed for a second or two and then
  // stopped for good.
  const {scroller, grow} = renderGrowingScroller();
  grow(0);
  expect(scroller.scrollTop).toBe(CONTENT_HEIGHT - WINDOW_HEIGHT);

  grow(200);
  grow(200);

  expect(scroller.scrollTop).toBe(CONTENT_HEIGHT + 400 - WINDOW_HEIGHT);
});

test('stops following once the reader scrolls away, however far the content grows', () => {
  const {scroller, grow} = renderGrowingScroller();
  grow(0);

  scroller.scrollTop = 120;
  grow(200);

  expect(scroller.scrollTop).toBe(120);
});

// A plan card tall enough that opening it at its own top leaves the bottom
// of the timeline far below the fold -- which is the real card's shape, and
// the only state in which the test below can fail.
const PLAN_CARD_HEIGHT = 1200;

// Mirrors the module's own FOLLOW_THRESHOLD_PX, which is private to it: the
// setup below is only meaningful if the anchored position sits further from
// the bottom than a reader following along ever would.
const FOLLOW_THRESHOLD_PX = 64;

test('leaves the confirmed plan where the card opened, not at its Start button', () => {
  // The reader never touches the scroller here: the anchored placement is
  // this hook's own work. Recording it as a scroll made "hasn't moved since"
  // read as "following the bottom", so clicking Start -- which swaps the
  // draft card for the confirmed one and re-anchors to the bottom -- threw
  // them past the whole plan. The scrolled-up test above cannot catch it,
  // because it moves scrollTop itself.
  const {scroller, arrive, confirm, contentHeight} = renderPlanScroller(
    600,
    true,
    PLAN_CARD_HEIGHT,
  );
  arrive();
  const anchored = scroller.scrollTop;
  const gap = contentHeight() - anchored - WINDOW_HEIGHT;
  expect(gap).toBeGreaterThan(FOLLOW_THRESHOLD_PX);

  confirm();

  expect(scroller.scrollTop).toBe(anchored);
});
