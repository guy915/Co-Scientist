import {screen} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  installLayoutMocks,
  renderLayout,
  systemApiMock,
} from './layout_test_support';

beforeEach(() => {
  installLayoutMocks();
});

it('does not show an overflow menu on run routes', () => {
  renderLayout('/runs/demo-ferroptosis/ideas');

  expect(screen.queryByRole('button', {name: 'More options'})).toBeNull();
});

it('shows the offline-mode chip when /status reports offline', async () => {
  systemApiMock.getSystemStatus.mockResolvedValue({
    mock_mode: true,
    llm_backend: 'offline',
    provider: 'engine',
    model_name: 'test/model',
  });

  renderLayout();

  expect(await screen.findByRole('status')).toHaveTextContent('Offline mode');
});
