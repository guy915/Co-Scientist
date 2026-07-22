import {act, render} from '@testing-library/react';
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import {TruncatedLabel} from './truncated_label';

// jsdom performs no real layout, so scrollWidth/clientWidth/scrollHeight/
// clientHeight are always 0. Replace them file-wide with a simple
// character-count model: the "container" size is a mutable variable tests
// can adjust to simulate resizes, and the "content" size is the node's
// current textContent length — close enough to real measurement for
// exercising the truncation algorithm deterministically.
let containerWidth = 20;
let containerHeight = 10;
let originalDescriptors: Record<string, PropertyDescriptor | undefined>;

/** Snapshots the layout property descriptors so afterAll can restore them. */
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

/** Installs the character-count layout model on HTMLElement.prototype. */
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

// Captures the ResizeObserver instance created for a render so tests can
// fire a resize notification manually (the app-wide test_setup stub is a
// no-op that never calls back).
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

/** Flushes the requestAnimationFrame fit() scheduled on mount. */
async function flushNextFrame() {
  await act(async () => {
    await new Promise(resolve => requestAnimationFrame(resolve));
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

describe('TruncatedLabel', () => {
  it('renders text unchanged when it fits within the container', async () => {
    const {container} = render(<TruncatedLabel text="short label" />);
    await flushNextFrame();
    expect(container.querySelector('span')!.textContent).toBe('short label');
  });

  it('truncates on a word boundary and appends an ellipsis when text overflows', async () => {
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

  it('applies the className prop to the rendered span', () => {
    const {container} = render(
      <TruncatedLabel text="hi" className="my-label" />,
    );
    expect(container.querySelector('span')).toHaveClass('my-label');
  });

  it('measures against height (not width) when lines > 1', async () => {
    // Wide enough that width-based measurement alone would never overflow,
    // but taller than containerHeight (10) in this character-count model.
    containerWidth = 1000;
    const text = 'one two three four five six seven eight nine ten';
    const {container} = render(<TruncatedLabel text={text} lines={2} />);
    await flushNextFrame();
    const result = container.querySelector('span')!.textContent!;
    expect(result.endsWith('…')).toBe(true);
    expect(result).not.toBe(text);
  });

  it('re-fits when the ResizeObserver reports a container size change', async () => {
    const text = 'alpha beta gamma delta';
    const {container} = render(<TruncatedLabel text={text} />);
    const span = container.querySelector('span')!;
    await flushNextFrame();
    expect(span.textContent).not.toBe(text); // narrow container truncates it

    containerWidth = 200; // widen: everything now fits
    const instance = FakeResizeObserver.instances.at(-1)!;
    act(() => instance.trigger());

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
    expect(span.textContent).not.toBe(text); // narrow container truncates it

    // Widen only after the initial sync + rAF fits already ran, so the
    // eventual match to the full text can only come from the fonts.ready
    // continuation.
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

    expect(span.textContent).toBe(text);
  });

  it('does not re-fit on visibilitychange while the tab is hidden', async () => {
    const text = 'alpha beta gamma delta';
    const {container} = render(<TruncatedLabel text={text} />);
    const span = container.querySelector('span')!;
    await flushNextFrame();
    const truncated = span.textContent;

    containerWidth = 200;
    Object.defineProperty(document, 'hidden', {
      value: true,
      configurable: true,
    });
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(span.textContent).toBe(truncated); // unchanged: tab still hidden

    Object.defineProperty(document, 'hidden', {
      value: false,
      configurable: true,
    });
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

  it('registers a ResizeObserver and visibilitychange listener on mount, and cleans up on unmount', async () => {
    const removeEventListenerSpy = vi.spyOn(document, 'removeEventListener');
    const cancelSpy = vi.spyOn(window, 'cancelAnimationFrame');
    const {unmount} = render(<TruncatedLabel text="hello" />);
    const instance = FakeResizeObserver.instances.at(-1)!;
    expect(instance.observe).toHaveBeenCalledTimes(1);

    unmount();

    expect(instance.disconnect).toHaveBeenCalledTimes(1);
    expect(cancelSpy).toHaveBeenCalled();
    expect(removeEventListenerSpy).toHaveBeenCalledWith(
      'visibilitychange',
      expect.any(Function),
    );
    removeEventListenerSpy.mockRestore();
    cancelSpy.mockRestore();
  });
});
