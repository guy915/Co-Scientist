import {act, render} from '@testing-library/react';
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  expect,
  it,
  vi,
} from 'vitest';
import {TruncatedLabel} from './truncated_label';

// jsdom measurements are zero; character counts provide deterministic overflow
// geometry.
let containerWidth = 20;
let containerHeight = 10;
let originalDescriptors: Record<string, PropertyDescriptor | undefined>;

function snapshotLayoutDescriptors(): Record<
  string,
  PropertyDescriptor | undefined
> {
  return {
    scrollWidth: Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'scrollWidth',
    ),
    clientWidth: Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'clientWidth',
    ),
    scrollHeight: Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'scrollHeight',
    ),
    clientHeight: Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'clientHeight',
    ),
  };
}

function installCharacterCountLayout() {
  Object.defineProperty(HTMLElement.prototype, 'scrollWidth', {
    configurable: true,
    get(this: HTMLElement) {
      return (this.textContent ?? '').length;
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get() {
      return containerWidth;
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return (this.textContent ?? '').length;
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get() {
      return containerHeight;
    },
  });
}

beforeAll(() => {
  originalDescriptors = snapshotLayoutDescriptors();
  installCharacterCountLayout();
});

afterAll(() => {
  for (const [key, descriptor] of Object.entries(originalDescriptors)) {
    if (descriptor) {
      Object.defineProperty(HTMLElement.prototype, key, descriptor);
    }
  }
});

// The global ResizeObserver stub never calls back; capture this observer for
// resize delivery.
class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  constructor(private readonly callback: ResizeObserverCallback) {
    FakeResizeObserver.instances.push(this);
  }
  trigger() {
    this.callback([], this as unknown as ResizeObserver);
  }
}
vi.stubGlobal('ResizeObserver', FakeResizeObserver);

async function flushNextFrame() {
  await act(async () => {
    await new Promise(resolve => requestAnimationFrame(resolve));
  });
}

// Fits batch one microtask later, so synchronous notifications still need a
// queue drain.
async function flushFitBatch() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  containerWidth = 20;
  containerHeight = 10;
  FakeResizeObserver.instances.length = 0;
});

afterEach(() => {
  Reflect.deleteProperty(document, 'fonts');
});

it('renders text unchanged when it fits within the container', async () => {
  const {container} = render(<TruncatedLabel text="short label" />);
  await flushNextFrame();
  expect(container.querySelector('span')!.textContent).toBe('short label');
});

it('truncates on a word boundary and appends an ellipsis', async () => {
  const text = 'abc def ghi jkl mno pqr stu vwx yz1 234';
  const {container} = render(<TruncatedLabel text={text} />);
  await flushNextFrame();
  expect(container.querySelector('span')!.textContent).toBe(
    'abc def ghi jkl mno…',
  );
});

it('clips the first word when even it alone does not fit', async () => {
  const text = 'x'.repeat(30);
  const {container} = render(<TruncatedLabel text={text} />);
  await flushNextFrame();
  expect(container.querySelector('span')!.textContent).toBe(`${text}…`);
});

it('measures against height (not width) when lines > 1', async () => {
  containerWidth = 1000;
  const text = 'one two three four five six seven eight nine ten';
  const {container} = render(<TruncatedLabel text={text} lines={2} />);
  await flushNextFrame();
  const result = container.querySelector('span')!.textContent!;
  expect(result.endsWith('…')).toBe(true);
  expect(result).not.toBe(text);
});

it('re-fits when the ResizeObserver reports a size change', async () => {
  const text = 'alpha beta gamma delta';
  const {container} = render(<TruncatedLabel text={text} />);
  const span = container.querySelector('span')!;
  await flushNextFrame();
  expect(span.textContent).not.toBe(text);

  containerWidth = 200;
  const instance = FakeResizeObserver.instances.at(-1)!;
  act(() => instance.trigger());

  // Writing during ResizeObserver delivery triggers browser loop errors; fit on
  // the next frame.
  expect(span.textContent).not.toBe(text);
  await flushNextFrame();
  expect(span.textContent).toBe(text);
});

it('re-fits after web fonts finish loading', async () => {
  let resolveFonts: () => void = () => {};
  const fontsReady = new Promise<void>(resolve => {
    resolveFonts = resolve;
  });
  Object.defineProperty(document, 'fonts', {
    value: {ready: fontsReady},
    configurable: true,
  });

  const text = 'alpha beta gamma delta';
  const {container} = render(<TruncatedLabel text={text} />);
  const span = container.querySelector('span')!;
  await flushNextFrame();
  expect(span.textContent).not.toBe(text);

  containerWidth = 200;
  await act(async () => {
    resolveFonts();
    await fontsReady;
  });

  expect(span.textContent).toBe(text);
});

it('re-fits when the tab becomes visible again', async () => {
  const text = 'alpha beta gamma delta';
  const {container} = render(<TruncatedLabel text={text} />);
  const span = container.querySelector('span')!;
  await flushNextFrame();
  expect(span.textContent).not.toBe(text);

  containerWidth = 200;
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await flushFitBatch();

  expect(span.textContent).toBe(text);
});

it('re-fits when the text prop changes', async () => {
  const {container, rerender} = render(<TruncatedLabel text="short" />);
  const span = container.querySelector('span')!;
  await flushNextFrame();
  expect(span.textContent).toBe('short');

  const longText = 'abc def ghi jkl mno pqr stu vwx yz1 234';
  rerender(<TruncatedLabel text={longText} />);
  await flushNextFrame();
  expect(span.textContent).toBe('abc def ghi jkl mno…');
});
