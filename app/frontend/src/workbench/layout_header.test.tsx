import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it} from 'vitest';
import {AudienceProvider} from './audience_context';
import {ShellHeader} from './layout_header';

function renderHeader() {
  return render(
    <MemoryRouter>
      <AudienceProvider>
        <ShellHeader
          navOpen={false}
          toggleNav={() => {}}
          startNewChat={() => {}}
          headerTitle=""
          activePanel={null}
          onTogglePanel={() => {}}
          logsControlRef={{current: null}}
        />
      </AudienceProvider>
    </MemoryRouter>,
  );
}

describe('ShellHeader audience control', () => {
  beforeEach(() => window.localStorage.clear());

  it('shows Logs for the general audience', () => {
    window.localStorage.setItem('cosci-audience', 'general');
    renderHeader();
    expect(screen.getByRole('button', {name: /Logs/i})).toBeInTheDocument();
  });

  it('shows the pilot control for sbi_ucd', () => {
    window.localStorage.setItem('cosci-audience', 'sbi_ucd');
    renderHeader();
    expect(
      screen.getByRole('button', {name: /Early access/i}),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /Logs/i})).toBeNull();
  });

  it('shows the team control for google', () => {
    window.localStorage.setItem('cosci-audience', 'google');
    renderHeader();
    expect(
      screen.getByRole('button', {name: /Team note/i}),
    ).toBeInTheDocument();
  });
});
