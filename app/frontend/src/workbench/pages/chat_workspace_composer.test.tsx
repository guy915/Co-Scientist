import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {
  installChatWorkspaceMocks,
  renderWorkspace,
} from './chat_workspace_test_helpers';

beforeEach(() => {
  installChatWorkspaceMocks();
});

describe('ChatWorkspace composer', () => {
  it('shows composer file and connector source controls', async () => {
    renderWorkspace();

    expect(screen.getByRole('button', {name: 'Files'})).toBeInTheDocument();
    const connectors = screen.getByRole('button', {name: 'Connectors'});
    expect(connectors).toBeInTheDocument();
    const sendButton = screen.getByRole('button', {name: 'Send'});
    expect(sendButton).toHaveAttribute('data-tooltip', 'Submit');
    expect(sendButton).toHaveClass('ucs-tooltip-anchor');
    expect(sendButton).toHaveClass('ucs-tooltip-top');

    fireEvent.click(connectors);

    expect(screen.getByRole('menu', {name: 'Connectors'})).toBeInTheDocument();
    expect(screen.getByText('Connectors')).toBeInTheDocument();
    expect(screen.getByText('PubMed')).toBeInTheDocument();
    expect(screen.queryByText('Google Search')).not.toBeInTheDocument();
    expect(screen.queryByText('Drive')).not.toBeInTheDocument();
    expect(screen.queryByText('SharePoint')).not.toBeInTheDocument();

    fireEvent.mouseDown(document.body);

    expect(
      screen.queryByRole('menu', {name: 'Connectors'}),
    ).not.toBeInTheDocument();
  });

  it('shows uploaded file previews in the composer', async () => {
    renderWorkspace();

    const fileInput = screen.getByLabelText('Upload files');
    fireEvent.change(fileInput, {
      target: {
        files: [
          new File(['abstract'], 'deep-research-report.md', {
            type: 'text/markdown',
          }),
        ],
      },
    });

    const filename = screen.getByText('deep-research-report.md');
    expect(filename).toBeInTheDocument();
    expect(filename.closest('.reference-attachment-card')).toHaveAttribute(
      'data-tooltip',
      'deep-research-report.md',
    );
    expect(screen.getByText('TXT')).toBeInTheDocument();
    expect(screen.getByText('Markdown')).toBeInTheDocument();
    expect(
      screen.getByRole('button', {name: 'Remove deep-research-report.md'}),
    ).toHaveAttribute('data-tooltip', 'Remove deep-research-report.md');
  });

  it('shows uploaded image previews in the composer', async () => {
    const createObjectURL = vi.fn(() => 'blob:preview-image');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    renderWorkspace();

    const fileInput = screen.getByLabelText('Upload files');
    fireEvent.change(fileInput, {
      target: {
        files: [
          new File(['image'], 'reference-shot.png', {
            type: 'image/png',
          }),
        ],
      },
    });

    expect(screen.getByAltText('reference-shot.png')).toHaveAttribute(
      'src',
      'blob:preview-image',
    );

    fireEvent.click(
      screen.getByRole('button', {name: 'Remove reference-shot.png'}),
    );

    expect(screen.queryByAltText('reference-shot.png')).toBeNull();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:preview-image');
  });

  it('previews a suggestion without moving the composer', async () => {
    renderWorkspace();

    const composer = await screen.findByRole('textbox');
    const originalComposerTop = composer
      .closest('.reference-composer')
      ?.getBoundingClientRect().top;

    const suggestion = screen.getByRole('button', {
      name: 'Find new therapeutic targets for M.tuberculosis by combining host-pathogen interaction datasets with recent literature.',
    });

    fireEvent.pointerEnter(suggestion);

    const preview = screen.getByText(
      'Find new therapeutic targets for M.tuberculosis by combining host-pathogen interaction datasets with recent literature.',
      {selector: '.reference-suggestion-preview'},
    );
    expect(preview).toBeInTheDocument();
    expect(preview).toHaveClass('visible');
    expect(preview.closest('.reference-suggestion-slot')).toContainElement(
      suggestion,
    );
    expect(
      composer.closest('.reference-composer')?.getBoundingClientRect().top,
    ).toBe(originalComposerTop);

    fireEvent.pointerLeave(suggestion);
    expect(preview).not.toHaveClass('visible');
  });

  it('fills the composer from a suggested prompt', () => {
    renderWorkspace();

    const suggestion = screen.getByRole('button', {
      name: 'Find new therapeutic targets for M.tuberculosis by combining host-pathogen interaction datasets with recent literature.',
    });

    fireEvent.click(suggestion);

    expect(screen.getByRole('textbox')).toHaveValue(
      'Find new therapeutic targets for M.tuberculosis by combining host-pathogen interaction datasets with recent literature.',
    );
    expect(suggestion).not.toHaveClass('selected');
    expect(suggestion).not.toHaveClass('is-previewed');
  });

  it('hides the suggestion preview after selecting a suggested prompt', () => {
    renderWorkspace();

    const suggestion = screen.getByRole('button', {
      name: 'Generate novel hypotheses for the link between synaptic pruning and treatment-resistant neuroinflammation.',
    });

    fireEvent.pointerEnter(suggestion);

    const preview = screen.getByText(
      'Generate novel hypotheses for the link between synaptic pruning and treatment-resistant neuroinflammation.',
      {selector: '.reference-suggestion-preview'},
    );
    expect(preview).toHaveClass('visible');

    fireEvent.click(suggestion);

    expect(preview).not.toHaveClass('visible');
    expect(suggestion).not.toHaveClass('is-previewed');
  });
});
