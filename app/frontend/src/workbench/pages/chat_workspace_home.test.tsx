import {screen} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
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
