import {Fragment, useState} from 'react';
import {act, render} from '@testing-library/react';
import {beforeEach, expect, test, vi} from 'vitest';
import {useChatTimelineScroll} from './chat_workspace';
import {
  CONFIRMED_SPEC_ITEM_ID,
  DRAFT_SPEC_ITEM_ID,
  type TimelineItem,
} from './chat_workspace_timeline';
import {type StartedSession} from './chat_timeline_run_spec_card';
import {TIMELINE_ANCHOR_ATTRIBUTE} from './chat_timeline_bubble';

// jsdom reports zero heights; give the scroller realistic overflow geometry.
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

// Mount before transcript rehydration to expose initial scrolling rather than
// preloaded state.
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
  const {scroller, populate} = renderFreshScroller();

  populate(makeItems(20));
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(CONTENT_HEIGHT);
});

test('leaves a reader who scrolled up alone once the initial load has settled', () => {
  const {scroller, populate} = renderFreshScroller();
  populate(makeItems(20));
  act(() => void vi.runAllTimers());

  scroller.scrollTop = 120;
  populate(makeItems(21));
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(120);
});

test('switching to a different chat without remounting still lands at the bottom', () => {
  // Chat route parameter changes reuse the hook without remounting or emptying
  // the transcript.
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

  // Browsers clamp scrollTop at content bounds; jsdom does not.
  expect(scroller.scrollTop).toBe(CONTENT_HEIGHT);
});

test('leaves the reader where they scrolled to', () => {
  const {scroller, grow} = renderScroller(120);

  grow();
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(120);
});

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
  // An announcement grows an existing card and must not retrigger its arrival
  // jump.
  const {scroller, grow} = renderAnnouncingScroller(120);

  grow();
  act(() => void vi.runAllTimers());

  expect(scroller.scrollTop).toBe(120);
});

// jsdom rects are zero; position the plan below the scroller to observe its
// anchor.
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
  const {scroller, arrive} = renderPlanScroller(600);

  arrive();

  expect(scroller.scrollTop).toBe(600 + ANCHOR_ON_SCREEN_OFFSET - 20);
});

// Clamp scrolling while content grows; fixed heights hide large-fragment
// following failures.
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
  // Measure following intent before DOM growth or a large fragment looks like
  // reader scrolling.
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
