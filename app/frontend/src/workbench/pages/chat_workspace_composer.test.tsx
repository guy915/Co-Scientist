import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  installChatWorkspaceMocks,
  renderWorkspace,
  stubStatusConnectors,
} from './chat_workspace_test_helpers';

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
  // With no /status answer the menu says so, rather than passing its
  // fallback off as the deployment's real source list.
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
  // The backend drops the row when a web search would not reach a
  // provider -- no key configured, or a key the provider now refuses.
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
