import {render, screen, fireEvent, waitFor} from '@testing-library/react';
import {describe, expect, it, afterEach, vi} from 'vitest';
import {MarkdownMessageRenderer as MarkdownMessage} from './markdown_message_renderer';

describe('markdown message', () => {
  describe('MarkdownMessage', () => {
    it('renders markdown structure rather than its source characters', () => {
      render(
        <MarkdownMessage
          content={'Pick one:\n\n- **Primary** cells\n- iPSC-derived'}
        />,
      );

      expect(screen.getByRole('list')).toBeInTheDocument();
      expect(screen.getAllByRole('listitem')).toHaveLength(2);
      expect(screen.getByText('Primary').tagName).toBe('STRONG');
      expect(screen.queryByText(/\*\*Primary\*\*/)).toBeNull();
    });

    it('gives emphasis weight but never a color of its own', () => {
      // Inherited foreground color keeps bold reasoning in the same voice.
      render(<MarkdownMessage content={'A **bold** word'} />);

      const strong = screen.getByText('bold');
      expect(strong.className).toContain('font-medium');
      expect(strong.className).not.toMatch(/text-/);
    });

    it('renders a table, which is what GFM support is for', () => {
      render(
        <MarkdownMessage
          content={'| Model | Cost |\n| --- | --- |\n| iPSC | High |'}
        />,
      );

      expect(screen.getByRole('table')).toBeInTheDocument();
      expect(screen.getByRole('columnheader', {name: 'Model'})).toBeVisible();
    });

    it('opens links in a new tab without handing over the opener', () => {
      render(<MarkdownMessage content="[PubMed](https://pubmed.gov)" />);

      const link = screen.getByRole('link', {name: 'PubMed'});
      expect(link).toHaveAttribute('href', 'https://pubmed.gov');
      expect(link).toHaveAttribute('target', '_blank');
      // Citation links must preserve the live workspace and withhold
      // opener/referrer access.
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    });

    it('does not render raw HTML embedded in model output', () => {
      // Model output is untrusted; raw HTML must remain inert text.
      render(
        <MarkdownMessage content={'<img src=x onerror="alert(1)"> and text'} />,
      );

      expect(document.querySelector('img')).toBeNull();
      expect(screen.getByText(/and text/)).toBeInTheDocument();
    });
  });
});

describe('markdown message blocks', () => {
  // Whole-message parsing adds inter-block whitespace that normal CSS
  // collapses; normalize it away.
  const normalize = (html: string) => html.replace(/>\s+</g, '><').trim();

  describe('MarkdownMessage per-block splitting', () => {
    it('renders identical DOM for a multi-block message, split or not', () => {
      const content = '# Heading\n\nA paragraph with **bold**.\n\n- one\n- two';
      const {container} = render(<MarkdownMessage content={content} />);
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
      // jsdom cannot apply compiled CSS; flat siblings preserve first:/last:
      // semantics.
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
      // Reference definitions are document-scoped, so splitting must fall back.
      render(
        <MarkdownMessage
          content={
            'See [docs][d] for details.\n\n[d]: https://example.com/docs'
          }
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

      expect(container.firstElementChild!.querySelector('div')).toBeNull();
      expect(screen.getByText(/plain text/)).toBeInTheDocument();
    });
  });
});

describe('markdown message code', () => {
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'clipboard');
  });

  function stubClipboard(writeText: ReturnType<typeof vi.fn>) {
    Object.defineProperty(navigator, 'clipboard', {
      value: {writeText},
      configurable: true,
    });
  }

  function codeHeaderText() {
    const button = screen.getByRole('button', {name: /copy code|copied/i});
    return button.parentElement?.textContent ?? '';
  }

  describe('MarkdownMessage fenced code blocks', () => {
    it("labels a fenced block with the fence's language", () => {
      render(<MarkdownMessage content={'```python\nprint(1)\n```'} />);

      expect(codeHeaderText()).toBe('python');
    });

    it('renders no language label when the fence names none', () => {
      render(<MarkdownMessage content={'```\nplain text\n```'} />);

      expect(codeHeaderText()).toBe('');
    });

    it('applies syntax-highlighting token classes inside the code', () => {
      const {container} = render(
        <MarkdownMessage content={'```python\ndef f():\n    return 1\n```'} />,
      );

      expect(
        container.querySelectorAll('[class*="hljs-"]').length,
      ).toBeGreaterThan(0);
    });

    it('zeroes the inner pre margin so the card opens/closes flush', () => {
      // User-agent pre margins add blank strips; jsdom can only verify the
      // override class.
      const {container} = render(
        <MarkdownMessage content={'```js\nconst x = 1;\n```'} />,
      );

      const pre = container.querySelector('pre');
      expect(pre?.className.split(' ')).toContain('m-0');
    });

    it('copies the block source to the clipboard and reports success', async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      stubClipboard(writeText);
      render(<MarkdownMessage content={'```js\nconst x = 1;\n```'} />);

      fireEvent.click(screen.getByRole('button', {name: /copy code/i}));

      await waitFor(() => expect(writeText).toHaveBeenCalled());
      expect(writeText.mock.calls[0][0]).toContain('const x = 1;');
      await waitFor(() =>
        expect(
          screen.getByRole('button', {name: 'Copied'}),
        ).toBeInTheDocument(),
      );
    });

    it('does not crash or leave an unhandled rejection when the clipboard rejects', async () => {
      const writeText = vi.fn().mockRejectedValue(new Error('denied'));
      stubClipboard(writeText);
      const {container} = render(
        <MarkdownMessage content={'```js\nconst x = 1;\n```'} />,
      );

      fireEvent.click(screen.getByRole('button', {name: /copy code/i}));

      await waitFor(() => expect(writeText).toHaveBeenCalled());
      // Highlighting splits code into spans, requiring textContent rather than
      // a single text node.
      expect(container.querySelector('code')?.textContent).toContain(
        'const x = 1;',
      );
      await waitFor(() =>
        expect(
          screen.getByRole('button', {name: 'Copied'}),
        ).toBeInTheDocument(),
      );
    });

    it('leaves inline code exactly as before -- no header, no copy button', () => {
      render(<MarkdownMessage content="Use `code` here." />);

      const code = screen.getByText('code');
      expect(code.tagName).toBe('CODE');
      expect(code.className).toBe(
        'rounded-md bg-cosci-hover px-1 py-0.5 font-mono text-[0.9em]',
      );
      expect(screen.queryByRole('button', {name: /copy/i})).toBeNull();
    });
  });
});
