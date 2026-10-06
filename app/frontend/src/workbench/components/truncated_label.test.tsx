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
