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

  it('drops inter-block blank lines rather than assigning them to a slice', () => {
    const content = 'a\n\n\n\nb';
    const blocks = splitMarkdownIntoBlocks(content);
    expect(blocks).toEqual(['a', 'b']);
    expect(blocks.join('')).toBe('ab');
  });

  it('renders whole when a reference definition sits in a later block', () => {
    const content =
      'See [docs][d].\n\nSome other paragraph.\n\n[d]: https://example.com';
    expect(splitMarkdownIntoBlocks(content)).toEqual([content]);
  });

  it('renders whole when a definition is nested inside a blockquote', () => {
    const content = '> [d]: https://example.com\n\nSee [docs][d].';
    expect(splitMarkdownIntoBlocks(content)).toEqual([content]);
  });

  it('renders whole when a top-level block is raw HTML', () => {
    const content = '<div>one</div>\n\n<div>two</div>';
    expect(splitMarkdownIntoBlocks(content)).toEqual([content]);
  });

  it('still splits when HTML appears only inline inside a paragraph', () => {
    // Inline HTML does not create the document-scope hazard of block HTML.
    const content = 'Text with <b>inline</b> html.\n\nSecond paragraph.';
    expect(splitMarkdownIntoBlocks(content)).toEqual([
      'Text with <b>inline</b> html.',
      'Second paragraph.',
    ]);
  });
});
