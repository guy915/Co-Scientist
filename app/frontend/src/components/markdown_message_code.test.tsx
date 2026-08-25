import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {MarkdownMessage} from './markdown_message';

afterEach(() => {
  Reflect.deleteProperty(navigator, 'clipboard');
});

function stubClipboard(writeText: ReturnType<typeof vi.fn>) {
  Object.defineProperty(navigator, 'clipboard', {
    value: {writeText},
    configurable: true,
  });
}

/** The header row's text, read off the copy button's parent element. */
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
    // The user-agent stylesheet gives <pre> a `margin: 1em 0` default.
    // jsdom does not apply the compiled Tailwind sheet, so the class is
    // the only thing this test can pin -- but it is also the actual fix:
    // without it, that UA margin opens a blank strip under the header bar
    // and another above the card's bottom edge, on top of the p-3 padding.
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
      expect(screen.getByRole('button', {name: 'Copied'})).toBeInTheDocument(),
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
    // The message survives: the code (split across highlight-token spans,
    // hence textContent rather than a single text node) is still on
    // screen, and the button still reports success -- copyText's
    // execCommand fallback absorbed the rejection, nothing unmounted or
    // threw past the click handler.
    expect(container.querySelector('code')?.textContent).toContain(
      'const x = 1;',
    );
    await waitFor(() =>
      expect(screen.getByRole('button', {name: 'Copied'})).toBeInTheDocument(),
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
