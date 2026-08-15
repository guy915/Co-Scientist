import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {MarkdownMessage} from './markdown_message';

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
    // The literal markdown must not survive into the rendered text.
    expect(screen.queryByText(/\*\*Primary\*\*/)).toBeNull();
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
    // A citation must not navigate the workspace away from a live chat, and
    // the opened page gets neither a window handle nor the referrer.
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('does not render raw HTML embedded in model output', () => {
    // This renders untrusted model output, so `rehype-raw` is deliberately
    // absent: an <img onerror> in a reply is text, never an element.
    render(
      <MarkdownMessage content={'<img src=x onerror="alert(1)"> and text'} />,
    );

    expect(document.querySelector('img')).toBeNull();
    expect(screen.getByText(/and text/)).toBeInTheDocument();
  });
});
