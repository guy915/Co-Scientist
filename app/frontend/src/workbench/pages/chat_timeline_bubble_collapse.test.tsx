import {fireEvent, screen} from '@testing-library/react';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';
import {renderBubble} from './chat_timeline_bubble_test_support';

const longContent = 'Long line of chat text. '.repeat(40);

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  // jsdom performs no real layout, so scrollHeight is always 0. Force a
  // measured full height that exceeds the four-line collapsed height so
  // the collapse/expand affordance renders.
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
    configurable: true,
    value: 500,
  });
});

afterEach(() => {
  Reflect.deleteProperty(HTMLElement.prototype, 'scrollHeight');
});

test('toggles expand/collapse synchronously under prefers-reduced-motion', () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({matches: true}) as unknown as (
      query: string,
    ) => MediaQueryList,
  );
  const {container} = renderBubble({content: longContent});

  const textSpan = container.querySelector('span')!;
  expect(textSpan.className).toContain('whitespace-normal');

  const expandButton = screen.getByLabelText('Expand');
  // The toggle button persists across expand/collapse (same DOM node),
  // so a single spy tracks blur calls across both clicks below.
  const blurSpy = vi.spyOn(expandButton, 'blur');

  // A pointer click (detail > 0) should blur afterward.
  fireEvent.click(expandButton, {detail: 1});

  expect(blurSpy).toHaveBeenCalledOnce();
  const collapseButton = screen.getByLabelText('Collapse');
  expect(textSpan.className).toContain('whitespace-pre-wrap');
  // Settled immediately (no rAF wait needed) under reduced motion.
  expect(textSpan.style.maxHeight).toBe('');

  // A keyboard-style activation (detail 0) should not blur again.
  fireEvent.click(collapseButton, {detail: 0});
  expect(blurSpy).toHaveBeenCalledOnce();
  expect(screen.getByLabelText('Expand')).toBeInTheDocument();
  expect(textSpan.className).toContain('whitespace-normal');
});

test('animates expand/collapse via requestAnimationFrame otherwise, settling on transition end', () => {
  vi.stubGlobal('matchMedia', undefined);
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    cb(0);
    return 0;
  });
  const {container} = renderBubble({content: longContent});
  const textSpan = container.querySelector('span')!;

  fireEvent.click(screen.getByLabelText('Expand'), {detail: 1});
  const expanded = screen.getByLabelText('Collapse');
  expect(expanded).toBeInTheDocument();
  // Not settled yet: the inline max-height still caps the full height
  // until the transition-end handler fires.
  expect(textSpan.style.maxHeight).toBe('500px');

  // A transitionend for an unrelated property is ignored.
  fireEvent.transitionEnd(textSpan, {propertyName: 'opacity'});
  expect(textSpan.style.maxHeight).toBe('500px');

  fireEvent.transitionEnd(textSpan, {propertyName: 'max-height'});
  expect(textSpan.style.maxHeight).toBe('');

  fireEvent.click(screen.getByLabelText('Collapse'), {detail: 1});
  expect(screen.getByLabelText('Expand')).toBeInTheDocument();
  fireEvent.transitionEnd(textSpan, {propertyName: 'max-height'});
  expect(textSpan.className).toContain('whitespace-normal');
});
