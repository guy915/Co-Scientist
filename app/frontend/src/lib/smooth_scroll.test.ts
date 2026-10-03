import {expect, it, vi, afterEach} from 'vitest';
import {smoothScrollToSection} from './smooth_scroll';

afterEach(() => {
  document.body.replaceChildren();
});

// jsdom has no layout; stub the measurements used by scrolling.
function stubRect(el: HTMLElement, rect: Partial<{top: number; left: number}>) {
  vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({
    top: rect.top ?? 0,
    left: rect.left ?? 0,
    bottom: 0,
    right: 0,
    width: 0,
    height: 0,
    x: rect.left ?? 0,
    y: rect.top ?? 0,
    toJSON() {
      return this;
    },
  });
}

function stubScrollSize(
  el: HTMLElement,
  scrollHeight: number,
  clientHeight: number,
) {
  Object.defineProperty(el, 'scrollHeight', {
    value: scrollHeight,
    configurable: true,
  });
  Object.defineProperty(el, 'clientHeight', {
    value: clientHeight,
    configurable: true,
  });
}

it('returns false when the target id does not exist', () => {
  expect(smoothScrollToSection('missing')).toBe(false);
});

it('scrolls a preferred pane container and returns true', () => {
  const pane = document.createElement('div');
  pane.className = 'idea-detail-pane';
  const target = document.createElement('div');
  target.id = 'section-1';
  pane.append(target);
  document.body.append(pane);

  stubRect(pane, {top: 20});
  stubRect(target, {top: 120});
  // jsdom does not implement Element.scrollTo.
  const scrollTo = vi.fn();
  (pane as unknown as {scrollTo: typeof scrollTo}).scrollTo = scrollTo;
  pane.scrollTop = 50;

  const result = smoothScrollToSection(
    'section-1',
    0,
    '.idea-detail-pane, .cosci-report-scroll',
  );

  expect(result).toBe(true);
  expect(scrollTo).toHaveBeenCalledWith({
    top: 50 + 120 - 20 - 0,
    behavior: 'smooth',
  });
});

it('finds a .cosci-report-scroll ancestor and applies the offset', () => {
  const pane = document.createElement('div');
  pane.className = 'cosci-report-scroll';
  const target = document.createElement('div');
  target.id = 'section-2';
  pane.append(target);
  document.body.append(pane);

  stubRect(pane, {top: 0});
  stubRect(target, {top: 200});
  const scrollTo = vi.fn();
  (pane as unknown as {scrollTo: typeof scrollTo}).scrollTo = scrollTo;
  pane.scrollTop = 0;

  const result = smoothScrollToSection(
    'section-2',
    16,
    '.idea-detail-pane, .cosci-report-scroll',
  );

  expect(result).toBe(true);
  expect(scrollTo).toHaveBeenCalledWith({
    top: 0 + 200 - 0 - 16,
    behavior: 'smooth',
  });
});

it('walks up to a scrollable ancestor with no preferred pane', () => {
  const outer = document.createElement('div');
  const scrollable = document.createElement('div');
  scrollable.style.overflowY = 'auto';
  const inert = document.createElement('div');
  const target = document.createElement('div');
  target.id = 'section-3';

  inert.append(target);
  scrollable.append(inert);
  outer.append(scrollable);
  document.body.append(outer);

  stubScrollSize(scrollable, 500, 200);
  const scrollTo = vi.fn();
  (scrollable as unknown as {scrollTo: typeof scrollTo}).scrollTo = scrollTo;

  const result = smoothScrollToSection('section-3');

  expect(result).toBe(true);
  expect(scrollTo).toHaveBeenCalledWith(
    expect.objectContaining({behavior: 'smooth'}),
  );
});

it('skips an overflow-y ancestor that does not actually overflow', () => {
  const scrollableButNotOverflowing = document.createElement('div');
  scrollableButNotOverflowing.style.overflowY = 'scroll';
  const target = document.createElement('div');
  target.id = 'section-4';
  scrollableButNotOverflowing.append(target);
  document.body.append(scrollableButNotOverflowing);

  const scrollIntoView = vi.fn();
  target.scrollIntoView = scrollIntoView;

  const result = smoothScrollToSection('section-4');

  expect(result).toBe(true);
  expect(scrollIntoView).toHaveBeenCalledWith({
    behavior: 'smooth',
    block: 'start',
  });
});

it('falls back to scrollIntoView when no scrollable ancestor is found', () => {
  const target = document.createElement('div');
  target.id = 'section-5';
  document.body.append(target);

  const scrollIntoView = vi.fn();
  target.scrollIntoView = scrollIntoView;

  const result = smoothScrollToSection('section-5');

  expect(result).toBe(true);
  expect(scrollIntoView).toHaveBeenCalledWith({
    behavior: 'smooth',
    block: 'start',
  });
});
