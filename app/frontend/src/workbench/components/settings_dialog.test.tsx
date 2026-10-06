import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {useState} from 'react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {ThemeProvider} from '../theme_context';
import {SettingsDialog} from './settings_dialog';

beforeEach(() => window.localStorage.clear());
afterEach(() => window.localStorage.clear());

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <ThemeProvider>
      <button onClick={() => setOpen(true)}>Open settings</button>
      {open && (
        <SettingsDialog
          section="appearance"
          onSectionChange={() => {}}
          onClose={() => setOpen(false)}
        />
      )}
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

function renderOpenDialog() {
  return render(
    <ThemeProvider>
      <button>Outside leading</button>
      <SettingsDialog
        section="appearance"
        onSectionChange={vi.fn()}
        onClose={vi.fn()}
      />
      <button>Outside trailing</button>
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
