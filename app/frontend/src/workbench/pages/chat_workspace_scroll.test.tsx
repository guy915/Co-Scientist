import {useState} from 'react';
import {act, render} from '@testing-library/react';
import {beforeEach, expect, test, vi} from 'vitest';
import {useChatTimelineScroll} from './chat_workspace';
import {type TimelineItem} from './chat_workspace_timeline';

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

test('keeps following the newest content when the reader is at the bottom', () => {
  const {scroller, grow} = renderScroller(BOTTOM);

  grow();
  act(() => void vi.runAllTimers());

  // Browsers clamp scrollTop at content bounds; jsdom does not.
  expect(scroller.scrollTop).toBe(CONTENT_HEIGHT);
});
