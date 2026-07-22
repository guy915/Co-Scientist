import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  CORPUS_CONNECTORS,
  installChatWorkspaceMocks,
  renderWorkspace,
  renderWorkspaceAs,
  stubStatusConnectors,
} from './chat_workspace_test_helpers';

beforeEach(() => {
  installChatWorkspaceMocks();
});

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
