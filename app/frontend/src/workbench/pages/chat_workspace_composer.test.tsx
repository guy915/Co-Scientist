import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it, vi, describe} from 'vitest';
import {
  installChatWorkspaceMocks,
  renderWorkspace,
  stubStatusConnectors,
} from './chat_workspace_test_helpers';
import {SUGGESTIONS} from './chat_home_stage';

describe('chat workspace composer', () => {
  beforeEach(() => {
    installChatWorkspaceMocks();
  });

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
    expect(screen.getByText('Checking available sources…')).toBeInTheDocument();
    expect(await screen.findByText(/Sources unavailable/)).toBeInTheDocument();
    expect(screen.queryByText('Google Search')).not.toBeInTheDocument();
    expect(screen.queryByText('Drive')).not.toBeInTheDocument();
    expect(screen.queryByText('SharePoint')).not.toBeInTheDocument();

    fireEvent.mouseDown(document.body);

    expect(
      screen.queryByRole('menu', {name: 'Connectors'}),
    ).not.toBeInTheDocument();
  });

  it('lists the web search connector from /status, on by default', async () => {
    stubStatusConnectors();
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', {name: 'Connectors'}));

    const webSearch = await screen.findByRole('menuitemcheckbox', {
      name: 'Web search',
    });
    expect(webSearch).toHaveAttribute('aria-checked', 'true');
    expect(
      screen.getByRole('menuitemcheckbox', {name: 'PubMed'}),
    ).toHaveAttribute('aria-checked', 'true');
  });

  it('omits the web search connector when /status omits it', async () => {
    stubStatusConnectors([{id: 'pubmed', display: 'PubMed'}]);
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', {name: 'Connectors'}));

    await screen.findByRole('menuitemcheckbox', {name: 'PubMed'});
    expect(
      screen.queryByRole('menuitemcheckbox', {name: 'Web search'}),
    ).not.toBeInTheDocument();
  });

  it('toggles web search independently of PubMed', async () => {
    stubStatusConnectors();
    renderWorkspace();

    fireEvent.click(screen.getByRole('button', {name: 'Connectors'}));
    const webSearch = await screen.findByRole('menuitemcheckbox', {
      name: 'Web search',
    });

    fireEvent.click(webSearch);

    expect(
      screen.getByRole('menuitemcheckbox', {name: 'Web search'}),
    ).toHaveAttribute('aria-checked', 'false');
    const pubmed = screen.getByRole('menuitemcheckbox', {name: 'PubMed'});
    expect(pubmed).toHaveAttribute('aria-checked', 'true');

    fireEvent.click(pubmed);

    expect(
      screen.getByRole('menuitemcheckbox', {name: 'PubMed'}),
    ).toHaveAttribute('aria-checked', 'false');
    expect(
      screen.getByRole('menuitemcheckbox', {name: 'Web search'}),
    ).toHaveAttribute('aria-checked', 'false');
  });
});

describe('chat workspace composer attachments', () => {
  beforeEach(() => {
    installChatWorkspaceMocks();
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
});

describe('chat workspace composer suggestions', () => {
  // Use the shared suggestions so prompt rewording cannot break interaction
  // checks.
  const [FIRST_SUGGESTION, SECOND_SUGGESTION] = SUGGESTIONS;

  beforeEach(() => {
    installChatWorkspaceMocks();
  });

  it('previews a suggestion without moving the composer', async () => {
    renderWorkspace();

    const composer = await screen.findByRole('textbox');
    const originalComposerTop = composer
      .closest('.reference-composer')
      ?.getBoundingClientRect().top;

    const suggestion = screen.getByRole('button', {
      name: FIRST_SUGGESTION.preview,
    });

    fireEvent.pointerEnter(suggestion);

    const preview = screen.getByText(FIRST_SUGGESTION.preview, {
      selector: '.reference-suggestion-preview',
    });
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
      name: FIRST_SUGGESTION.preview,
    });

    fireEvent.click(suggestion);

    expect(screen.getByRole('textbox')).toHaveValue(FIRST_SUGGESTION.prompt);
    expect(suggestion).not.toHaveClass('selected');
    expect(suggestion).not.toHaveClass('is-previewed');
  });

  it('hides the suggestion preview after selecting a suggested prompt', () => {
    renderWorkspace();

    const suggestion = screen.getByRole('button', {
      name: SECOND_SUGGESTION.preview,
    });

    fireEvent.pointerEnter(suggestion);

    const preview = screen.getByText(SECOND_SUGGESTION.preview, {
      selector: '.reference-suggestion-preview',
    });
    expect(preview).toHaveClass('visible');

    fireEvent.click(suggestion);

    expect(preview).not.toHaveClass('visible');
    expect(suggestion).not.toHaveClass('is-previewed');
  });
});
