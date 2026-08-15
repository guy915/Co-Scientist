import {useState} from 'react';
import {act, render} from '@testing-library/react';
import {beforeEach, expect, test, vi} from 'vitest';
import {useChatTimelineScroll} from './chat_workspace_scroll';
import {type TimelineItem} from './chat_workspace_timeline';

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
