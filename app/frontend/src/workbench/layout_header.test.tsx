import {render, screen} from '@testing-library/react';
import {useEffect} from 'react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it} from 'vitest';
import {type Audience, AudienceProvider, useAudience} from './audience_context';
import {ShellHeader} from './layout_header';

// Drives the provider through its public setter. Seeding localStorage would
// not work: the provider deliberately drops the stored value on mount while
// the mode controls are being designed (see RESTORE_ON_MOUNT).
function SetAudience({audience}: {audience: Audience | null}) {
  const {setAudience} = useAudience();
  useEffect(() => {
    if (audience) setAudience(audience);
  }, [audience, setAudience]);
  return null;
}

function renderHeader(audience: Audience | null = null) {
  return render(
    <MemoryRouter>
      <AudienceProvider>
        <SetAudience audience={audience} />
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
