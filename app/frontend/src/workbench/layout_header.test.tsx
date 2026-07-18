import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it} from 'vitest';
import {type Audience, AudienceProvider} from './audience_context';
import {ShellHeader} from './layout_header';

// Seeding localStorage would not drive this: the provider deliberately drops
// the stored value on mount while the mode controls are being designed (see
// RESTORE_ON_MOUNT), so the audience is declared to the provider directly.
function renderHeader(audience?: Audience) {
  return render(
    <MemoryRouter>
      <AudienceProvider initialAudience={audience}>
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
    renderHeader('general');
    expect(screen.getByRole('button', {name: /Logs/i})).toBeInTheDocument();
  });

  it('shows the pilot control for sbi_ucd', () => {
    renderHeader('sbi_ucd');
    expect(
      screen.getByRole('button', {name: /Early access/i}),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /Logs/i})).toBeNull();
  });

  it('shows the team control for google', () => {
    renderHeader('google');
    expect(
      screen.getByRole('button', {name: /Team note/i}),
    ).toBeInTheDocument();
  });
});
