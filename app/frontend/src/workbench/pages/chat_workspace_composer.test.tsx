import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it, describe} from 'vitest';
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
});

describe('chat workspace composer suggestions', () => {
  // Use the shared suggestions so prompt rewording cannot break interaction
  // checks.
  const [FIRST_SUGGESTION] = SUGGESTIONS;

  beforeEach(() => {
    installChatWorkspaceMocks();
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
});
