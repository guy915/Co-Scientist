import type {Mock} from 'vitest';
import {describe, expect, it, vi} from 'vitest';
import {render} from '@testing-library/react';
import type {Options} from 'react-markdown';
import {MarkdownMessage} from './markdown_message';

// react-markdown does its own remark parse per invocation, so "does this
// block re-render" is only observable by counting invocations of the
// component itself -- vi.fn wraps the real implementation so behavior is
// unchanged, but every call (and the props it was called with) is recorded.
vi.mock('react-markdown', async importOriginal => {
  const actual = await importOriginal<typeof import('react-markdown')>();
  return {...actual, default: vi.fn(actual.default)};
});

const BLOCK_ONE = 'First paragraph text here that stays fixed.';

/** Streams `content` into `component` one `rerender` per element of `steps`. */
function streamInto(content: string, steps: string[]) {
  const {rerender} = render(<MarkdownMessage content={content} />);
  for (const step of steps) {
    content += step;
    rerender(<MarkdownMessage content={content} />);
  }
}

describe('MarkdownMessage block memoization', () => {
  it('does not re-invoke react-markdown for a completed block while a later block grows', async () => {
    const Markdown = (await import('react-markdown'))
      .default as unknown as Mock;
    Markdown.mockClear();

    streamInto(`${BLOCK_ONE}\n\nSecond`, [
      ' paragraph',
      ' keeps',
      ' growing',
      ' with',
      ' more',
      ' words',
    ]);

    // Once split into per-block components, block one's slice never changes
    // after the first render, so React.memo bails out on every later
    // rerender: exactly one invocation with that exact source slice, however
    // many times the message as a whole re-renders.
    const callsForBlockOne = Markdown.mock.calls.filter(
      call => (call[0] as Options).children === BLOCK_ONE,
    );
    expect(callsForBlockOne).toHaveLength(1);
  });
});
