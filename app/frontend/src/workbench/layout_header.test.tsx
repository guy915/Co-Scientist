import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it} from 'vitest';
import {type Audience, AudienceProvider} from './audience_context';
import {GOOGLE_NOTE} from './audience_content';
import {ShellHeader} from './layout_header';

// The audience is declared to the provider directly rather than seeded into
// localStorage, so these cases do not depend on the storage read.
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
    expect(screen.getByRole('button', {name: /Feedback/i})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /Logs/i})).toBeNull();
  });

  it('shows the team control for google', () => {
    renderHeader('google');
    expect(
      screen.getByRole('button', {name: GOOGLE_NOTE.label}),
    ).toBeInTheDocument();
  });
});
