import {fireEvent, render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {
  installChatWorkspaceMocks,
  renderWorkspace,
} from './chat_workspace_test_helpers';
import {SUGGESTIONS} from './chat_home_stage';
import {AudienceProvider, type Audience} from '../audience_context';
import {RunHistoryProvider} from '../hooks/run_history_context';
import {ChatWorkspace} from './chat_workspace';

// Local render that pins the audience: the Lab papers connector row is gated to
// the sbi_ucd audience, and the shared renderWorkspace helper always resolves
// to 'general'. Mirrors that helper's provider stack so the `@/api/runs` mock
// it registers still applies.
function renderWorkspaceAs(audience: Audience) {
  return render(
    <MemoryRouter>
      <AudienceProvider initialAudience={audience}>
        <RunHistoryProvider>
          <ChatWorkspace />
        </RunHistoryProvider>
      </AudienceProvider>
    </MemoryRouter>,
  );
}

// The exact suggestion copy lives in one place (SUGGESTIONS); reference it by
// index here so re-wording a prompt never breaks these interaction tests.
const [FIRST_SUGGESTION, SECOND_SUGGESTION] = SUGGESTIONS;

beforeEach(() => {
  installChatWorkspaceMocks();
});

// Drives the connectors menu off a real /status payload. Only the connectors
// list is read by the menu, so the rest of the response is left out. Must run
// after installChatWorkspaceMocks, which clears stubbed globals.
function stubStatusConnectors(
  connectors: {id: string; display: string}[] = [
    {id: 'pubmed', display: 'PubMed'},
    {id: 'web_search', display: 'Web search'},
  ],
) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({connectors}),
      text: async () => '',
    })) as unknown as typeof fetch,
  );
}

describe('ChatWorkspace composer', () => {
  describe('connectors menu', () => {
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

      expect(
        screen.getByRole('menu', {name: 'Connectors'}),
      ).toBeInTheDocument();
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

    it('lists the web search connector reported by /status, on by default', async () => {
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

    it('omits the web search connector when /status does not report it', async () => {
      // The MCP server only advertises its web search tool when a provider key
      // is configured, so a deployment without one must not offer the row.
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

      // Turning web search off must leave the literature toggle untouched: both
      // rows used to share one boolean, so this is the regression guard.
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

  // Backend-ordered connectors (web, pubmed, corpus) including the SBI/UCD
  // paper corpus, used by the audience-gated Lab papers tests below.
  const CORPUS_CONNECTORS = [
    {id: 'web_search', display: 'Web search'},
    {id: 'pubmed', display: 'PubMed'},
    {id: 'paper_corpus', display: 'Lab papers'},
  ];

  describe('Lab papers connector', () => {
    it('shows the Lab papers connector for the sbi_ucd audience, on by default', async () => {
      stubStatusConnectors(CORPUS_CONNECTORS);
      renderWorkspaceAs('sbi_ucd');

      fireEvent.click(screen.getByRole('button', {name: 'Connectors'}));

      const labPapers = await screen.findByRole('menuitemcheckbox', {
        name: 'Lab papers',
      });
      expect(labPapers).toHaveAttribute('aria-checked', 'true');
    });

    it('hides the Lab papers connector for a non-sbi audience even when advertised', async () => {
      stubStatusConnectors(CORPUS_CONNECTORS);
      renderWorkspace();

      fireEvent.click(screen.getByRole('button', {name: 'Connectors'}));

      // The other advertised rows still render; only the corpus row is gated.
      await screen.findByRole('menuitemcheckbox', {name: 'Web search'});
      expect(
        screen.queryByRole('menuitemcheckbox', {name: 'Lab papers'}),
      ).not.toBeInTheDocument();
    });

    it('toggles Lab papers independently of PubMed and web search', async () => {
      stubStatusConnectors(CORPUS_CONNECTORS);
      renderWorkspaceAs('sbi_ucd');

      fireEvent.click(screen.getByRole('button', {name: 'Connectors'}));
      const labPapers = await screen.findByRole('menuitemcheckbox', {
        name: 'Lab papers',
      });

      fireEvent.click(labPapers);

      expect(
        screen.getByRole('menuitemcheckbox', {name: 'Lab papers'}),
      ).toHaveAttribute('aria-checked', 'false');
      expect(
        screen.getByRole('menuitemcheckbox', {name: 'PubMed'}),
      ).toHaveAttribute('aria-checked', 'true');
      expect(
        screen.getByRole('menuitemcheckbox', {name: 'Web search'}),
      ).toHaveAttribute('aria-checked', 'true');
    });
  });

  describe('file attachments', () => {
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

  describe('suggested prompts', () => {
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

      // The card previews one sentence, but selecting it fills the full prompt.
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
});
