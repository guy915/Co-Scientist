import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import {AudienceProvider} from '../audience_context';
import {AudienceGate} from './audience_dialog';
import {AffiliationSection} from './settings_dialog';

function renderGate() {
  return render(
    <AudienceProvider>
      <AudienceGate />
    </AudienceProvider>,
  );
}

describe('AudienceGate', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it('shows the dialog when no audience is stored', () => {
    renderGate();
    expect(
      screen.getByRole('dialog', {name: /affiliation/i}),
    ).toBeInTheDocument();
  });

  it('hides the dialog after a choice and persists it', async () => {
    renderGate();
    await userEvent.click(
      screen.getByRole('button', {name: /SBI \/ UCD researcher/i}),
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(window.localStorage.getItem('cosci-audience')).toBe('sbi_ucd');
  });

  it('does not show the dialog when an audience is already stored', () => {
    window.localStorage.setItem('cosci-audience', 'general');
    renderGate();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('AffiliationSection', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it('changes the stored audience when a new option is picked', async () => {
    window.localStorage.setItem('cosci-audience', 'general');
    render(
      <AudienceProvider>
        <AffiliationSection />
      </AudienceProvider>,
    );
    await userEvent.click(
      screen.getByRole('button', {name: /Google AI Co-Scientist team/i}),
    );
    expect(window.localStorage.getItem('cosci-audience')).toBe('google');
  });
});
