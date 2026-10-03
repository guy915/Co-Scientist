import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, expect, it, describe} from 'vitest';
import {
  installLayoutMocks,
  renderLayout,
  systemApiMock,
} from './layout_test_support';
import {ShellHeader} from './layout_header';

describe('layout header', () => {
  function renderHeader(activePanel: 'logs' | 'settings' | null = null) {
    return render(
      <MemoryRouter>
        <ShellHeader
          navOpen={false}
          toggleNav={() => {}}
          startNewChat={() => {}}
          headerTitle=""
          activePanel={activePanel}
          onTogglePanel={() => {}}
          logsControlRef={{current: null}}
          session={null}
          runStatus={undefined}
        />
      </MemoryRouter>,
    );
  }

  beforeEach(() => installLayoutMocks());

  it('always shows the Logs control', () => {
    renderHeader();
    expect(screen.getByRole('button', {name: /Logs/i})).toBeInTheDocument();
  });
});

describe('layout header status', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  it('does not show an overflow menu on run routes', () => {
    renderLayout('/runs/demo-ferroptosis/ideas');

    expect(screen.queryByRole('button', {name: 'More options'})).toBeNull();
  });

  it('shows the offline-mode chip when /status reports offline', async () => {
    systemApiMock.getSystemStatus.mockResolvedValue({
      llm_backend: 'offline',
      provider: 'engine',
      model_name: 'test/model',
    });

    renderLayout();

    expect(await screen.findByRole('status')).toHaveTextContent('Offline mode');
  });
});
