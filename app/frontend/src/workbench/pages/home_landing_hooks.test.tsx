import {act, render, renderHook} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {shapePath, useReducedMotion, useShapeMorph} from './home_landing_hooks';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it('follows the reduced-motion preference as it changes', () => {
  let onChange = () => {};
  const query = {
    matches: true,
    addEventListener: (_type: string, listener: () => void) => {
      onChange = listener;
    },
    removeEventListener: vi.fn(),
  };
  vi.stubGlobal('matchMedia', () => query);
  const {result} = renderHook(() => useReducedMotion());
  expect(result.current).toBe(true);

  query.matches = false;
  act(() => onChange());

  expect(result.current).toBe(false);
});

it.each([true, false])(
  'morphs the shape to a circle (reduced motion: %s)',
  reduce => {
    vi.stubGlobal('requestAnimationFrame', (step: (now: number) => void) =>
      step(performance.now() + 1000),
    );
    function Shape() {
      const {pathRef, toCircle} = useShapeMorph('pill', reduce);
      return (
        <svg>
          <path ref={pathRef} d={shapePath('pill')} onClick={toCircle} />
        </svg>
      );
    }
    const {container} = render(<Shape />);
    const path = container.querySelector('path')!;

    path.dispatchEvent(new MouseEvent('click', {bubbles: true}));

    expect(path.getAttribute('d')).toBe(shapePath('circle'));
  },
);
