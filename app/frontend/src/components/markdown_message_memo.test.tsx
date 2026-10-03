import type {Mock} from 'vitest';
import {describe, expect, it, vi} from 'vitest';
import {render} from '@testing-library/react';
import type {Options} from 'react-markdown';
import {MarkdownMessageRenderer as MarkdownMessage} from './markdown_message_renderer';

// Count real renderer invocations because react-markdown parses on each
// invocation.
vi.mock('react-markdown', async importOriginal => {
  const actual = await importOriginal<typeof import('react-markdown')>();
  return {...actual, default: vi.fn(actual.default)};
});

const BLOCK_ONE = 'First paragraph text here that stays fixed.';

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

    const callsForBlockOne = Markdown.mock.calls.filter(
      call => (call[0] as Options).children === BLOCK_ONE,
    );
    expect(callsForBlockOne).toHaveLength(1);
  });
});
