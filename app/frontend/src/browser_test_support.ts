import {vi} from 'vitest';

// jsdom lacks matchMedia; leaving it unstubbed silently exercises desktop.
export function stubViewport(mobile: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: mobile,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}
