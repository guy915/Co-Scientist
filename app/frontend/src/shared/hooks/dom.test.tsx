import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {useOverflowing} from './dom';

describe('use overflowing', () => {
  // jsdom has no layout engine; drive the hook's measurements explicitly.
  function stubGeometry(
    clientHeight: number,
    childTops: number[],
    childHeight: number,
  ) {
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.dataset.role === 'box' ? clientHeight : childHeight;
      },
    });
    HTMLElement.prototype.getBoundingClientRect = function () {
      const index = Number(this.dataset.index ?? -1);
      const top = index >= 0 ? childTops[index] : 0;
      return {top, bottom: top + childHeight} as DOMRect;
    };
  }

  function Probe({count}: {count: number}) {
    const [ref, overflowing] = useOverflowing<HTMLDivElement>();
    return (
      <div ref={ref} data-role="box">
        <span data-testid="state">{String(overflowing)}</span>
        {Array.from({length: count}, (_, index) => (
          <p key={index} data-index={index}>
            chat {index}
          </p>
        ))}
      </div>
    );
  }

  describe('useOverflowing', () => {
    it('reports no overflow when the children fit the box', () => {
      stubGeometry(100, [0, 30, 60], 30);
      render(<Probe count={3} />);
      expect(screen.getByTestId('state')).toHaveTextContent('false');
    });

    it('reports overflow when the children outrun the box', () => {
      stubGeometry(100, [0, 30, 60, 90, 120], 30);
      render(<Probe count={5} />);
      expect(screen.getByTestId('state')).toHaveTextContent('true');
    });
  });
});
