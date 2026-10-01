import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {
  installChatWorkspaceMocks,
  renderWorkspace,
} from './chat_workspace_test_helpers';

beforeEach(() => {
  installChatWorkspaceMocks();
});

it('opens on the reference-style Co-Scientist home screen', async () => {
  renderWorkspace();

  expect(
    screen.getByRole('heading', {
      name: 'What breakthrough should we make today?',
    }),
  ).toBeInTheDocument();
  expect(screen.getByText('Recents')).toBeInTheDocument();
  expect(screen.getByText('Frame the research goal')).toBeInTheDocument();
  expect(screen.getByText('Generate hypotheses')).toBeInTheDocument();
  expect(screen.getByText('Pressure-test the best ideas')).toBeInTheDocument();
  expect(screen.queryByText('AI Co-Scientist')).toBeNull();
  expect(
    screen.getByText('Start a new research goal to begin'),
  ).toBeInTheDocument();
  expect(screen.getByRole('textbox')).toBeInTheDocument();
  expect(
    await screen.findByText(/ferroptosis in pancreatic cancer cells/i, {
      selector: '.reference-recent-description',
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('link', {
      name: /ferroptosis in pancreatic cancer cells/i,
    }),
  ).toHaveAttribute('href', '/runs/demo-ferroptosis/details');
});

// The home still opens on the chat; the landing page waits below it, behind
// one quiet line under the composer that scrolls to it.
it('points from the composer down to the landing page', async () => {
  renderWorkspace();
  const hint = screen.getByRole('button', {
    name: 'Scroll to see how Co-Scientist works',
  });
  expect(
    await screen.findByRole('navigation', {name: 'Landing sections'}),
  ).toBeInTheDocument();
  const scrollIntoView = vi.fn();
  Element.prototype.scrollIntoView = scrollIntoView;
  fireEvent.click(hint);
  expect(scrollIntoView.mock.contexts[0]).toBe(
    document.getElementById('landing'),
  );
});
