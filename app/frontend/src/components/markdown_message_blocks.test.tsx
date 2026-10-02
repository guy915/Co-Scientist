import {describe, expect, it} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MarkdownMessageRenderer as MarkdownMessage} from './markdown_message_renderer';

// The whole-message renderer emits a whitespace-only text node ("\n")
// between top-level block elements; splitting parses each block in
// isolation and never produces one. That whitespace collapses under normal
// CSS whitespace handling either way, so it is irrelevant to what the
// reader sees -- normalize it away rather than asserting on it.
const normalize = (html: string) => html.replace(/>\s+</g, '><').trim();

describe('MarkdownMessage per-block splitting', () => {
  it('renders identical DOM for a multi-block message, split or not', () => {
    const content = '# Heading\n\nA paragraph with **bold**.\n\n- one\n- two';
    const {container} = render(<MarkdownMessage content={content} />);
    // A single block by construction: the whole-message path, unaffected by
    // splitting, is what "identical to before" is measured against.
    const {container: singleBlock} = render(
      <MarkdownMessage content="A paragraph." />,
    );

    expect(normalize(container.firstElementChild!.innerHTML)).toBe(
      '<p class="first:mt-0 last:mb-0 mt-3 mb-1.5 font-medium">Heading</p>' +
        '<p class="first:mt-0 last:mb-0 my-2 leading-[1.55]">A paragraph with <strong class="font-medium">bold</strong>.</p>' +
        '<ul class="first:mt-0 last:mb-0 my-2 list-disc space-y-1 pl-5"><li class="leading-[1.5]">one</li><li class="leading-[1.5]">two</li></ul>',
    );
    expect(normalize(singleBlock.firstElementChild!.innerHTML)).toBe(
      '<p class="first:mt-0 last:mb-0 my-2 leading-[1.55]">A paragraph.</p>',
    );
  });

  it('keeps every block a direct sibling of the wrapper, in source order', () => {
    // This is the structural fact that keeps `first:`/`last:` correct after
    // splitting: those are DOM-tree pseudo-classes, and jsdom does not
    // apply Tailwind's compiled CSS, so this is the honest way to pin it --
    // no extra wrapper element per block, same flat sibling list as one
    // instance would have produced.
    const content = '# Heading\n\nA paragraph.\n\n- one\n- two';
    const {container} = render(<MarkdownMessage content={content} />);
    const wrapper = container.firstElementChild!;

    expect(Array.from(wrapper.children).map(el => el.tagName)).toEqual([
      'P',
      'P',
      'UL',
    ]);
    expect(wrapper.firstElementChild!.textContent).toBe('Heading');
    expect(wrapper.lastElementChild!.tagName).toBe('UL');
  });

  it('resolves a reference-style link whose definition sits in a later block', () => {
    // Definitions are document-scoped: severed from its block, this link
    // would render as literal `[docs][d]` text. Proves the whole-message
    // fallback actually fires, not just that the splitter reports it would.
    render(
      <MarkdownMessage
        content={'See [docs][d] for details.\n\n[d]: https://example.com/docs'}
      />,
    );

    expect(screen.getByRole('link', {name: 'docs'})).toHaveAttribute(
      'href',
      'https://example.com/docs',
    );
  });

  it('still escapes raw HTML that spans multiple top-level blocks', () => {
    const {container} = render(
      <MarkdownMessage
        content={'<div>one</div>\n\n<div>two</div>\n\nplain text'}
      />,
    );

    // querySelector on the wrapper excludes the wrapper itself, so this
    // finds only an element the markdown produced -- none, since the two
    // HTML blocks must stay literal text.
    expect(container.firstElementChild!.querySelector('div')).toBeNull();
    expect(screen.getByText(/plain text/)).toBeInTheDocument();
  });
});
