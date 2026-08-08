import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {useState} from 'react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {AudienceProvider} from '../audience_context';
import {ThemeProvider} from '../theme_context';
import {SettingsDialog} from './settings_dialog';

// O1: the Settings dialog (also the first-visit affiliation chooser, which
// AudienceGate opens on its Affiliation section) must trap Tab within
// itself, mark the page behind it inert, and hand focus back to whatever
// opened it once it closes.

beforeEach(() => window.localStorage.clear());
afterEach(() => window.localStorage.clear());

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <ThemeProvider>
      <AudienceProvider initialAudience="general">
        <button onClick={() => setOpen(true)}>Open settings</button>
        {open && (
          <SettingsDialog
            section="appearance"
            onSectionChange={() => {}}
            onClose={() => setOpen(false)}
          />
        )}
      </AudienceProvider>
    </ThemeProvider>
  );
}

it('returns focus to the control that opened it once it closes', async () => {
  const user = userEvent.setup();
  render(<DialogHarness />);

  const opener = screen.getByRole('button', {name: 'Open settings'});
  await user.click(opener);
  await screen.findByRole('button', {name: 'Close settings'});

  await user.keyboard('{Escape}');

  await waitFor(() => expect(opener).toHaveFocus());
});

function renderOpenDialog(
  section: 'appearance' | 'affiliation' = 'appearance',
) {
  return render(
    <ThemeProvider>
      <AudienceProvider initialAudience="general">
        <button>Outside leading</button>
        <SettingsDialog
          section={section}
          onSectionChange={vi.fn()}
          onClose={vi.fn()}
        />
        <button>Outside trailing</button>
      </AudienceProvider>
    </ThemeProvider>,
  );
}

it('traps forward Tab, wrapping past the last focusable element', async () => {
  const user = userEvent.setup();
  renderOpenDialog();

  const closeButton = await screen.findByRole('button', {
    name: 'Close settings',
  });
  const lastThemeButton = screen.getByRole('button', {name: 'Dark'});

  lastThemeButton.focus();
  await user.tab();

  expect(closeButton).toHaveFocus();
});

it('traps backward Shift+Tab, wrapping past the first focusable element', async () => {
  const user = userEvent.setup();
  renderOpenDialog();

  const closeButton = await screen.findByRole('button', {
    name: 'Close settings',
  });
  const lastThemeButton = screen.getByRole('button', {name: 'Dark'});

  closeButton.focus();
  await user.tab({shift: true});

  expect(lastThemeButton).toHaveFocus();
});

it('traps focus on the affiliation section the first-visit gate opens', async () => {
  const user = userEvent.setup();
  renderOpenDialog('affiliation');

  const closeButton = await screen.findByRole('button', {
    name: 'Close settings',
  });
  const radios = screen.getAllByRole('radio');
  radios[radios.length - 1].focus();
  await user.tab();

  expect(closeButton).toHaveFocus();
});

function InertHarness() {
  const [open, setOpen] = useState(true);
  return (
    <ThemeProvider>
      <AudienceProvider initialAudience="general">
        <button>Outside</button>
        {open && (
          <SettingsDialog
            section="appearance"
            onSectionChange={vi.fn()}
            onClose={() => setOpen(false)}
          />
        )}
      </AudienceProvider>
    </ThemeProvider>
  );
}

it('marks the page behind it inert while open, and clears that on close', async () => {
  const user = userEvent.setup();
  render(<InertHarness />);

  const outside = screen.getByRole('button', {name: 'Outside'});
  expect(outside).toHaveAttribute('inert');

  await user.keyboard('{Escape}');

  await waitFor(() => expect(outside).not.toHaveAttribute('inert'));
});
