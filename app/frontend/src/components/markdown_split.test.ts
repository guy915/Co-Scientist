import {describe, expect, it} from 'vitest';
import {splitMarkdownIntoBlocks} from './markdown_message_renderer';

describe('splitMarkdownIntoBlocks', () => {
  it('returns nothing for empty content', () => {
    expect(splitMarkdownIntoBlocks('')).toEqual([]);
  });

  it('splits a multi-block message into one exact slice per block', () => {
    const content = 'First paragraph.\n\n- one\n- two\n\n# Heading';
    expect(splitMarkdownIntoBlocks(content)).toEqual([
      'First paragraph.',
      '- one\n- two',
      '# Heading',
    ]);
  });

  it('renders whole when a reference definition sits in a later block', () => {
    const content =
      'See [docs][d].\n\nSome other paragraph.\n\n[d]: https://example.com';
    expect(splitMarkdownIntoBlocks(content)).toEqual([content]);
  });

  it('renders whole when a top-level block is raw HTML', () => {
    const content = '<div>one</div>\n\n<div>two</div>';
    expect(splitMarkdownIntoBlocks(content)).toEqual([content]);
  });
});
