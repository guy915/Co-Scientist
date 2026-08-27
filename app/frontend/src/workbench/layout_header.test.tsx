import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, expect, it} from 'vitest';
import {ShellHeader} from './layout_header';

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
      />
    </MemoryRouter>,
  );
}

beforeEach(() => window.localStorage.clear());

it('always shows the Logs control', () => {
  renderHeader();
  expect(screen.getByRole('button', {name: /Logs/i})).toBeInTheDocument();
});
