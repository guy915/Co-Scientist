import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {installLayoutMocks, renderLayout} from './layout_test_support';

beforeEach(() => {
  installLayoutMocks();
});

it('opens the settings menu and dismisses on outside click', async () => {
  renderLayout();

  fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
  expect(
    screen.getByRole('menuitem', {name: 'Appearance'}),
  ).toBeInTheDocument();
  expect(screen.getByRole('menuitem', {name: 'Model'})).toBeInTheDocument();
  expect(screen.getByRole('menuitem', {name: 'Help'})).toBeInTheDocument();
  // The menu itself has no location line and no theme control; those move
  // into the dialog.
  expect(screen.queryByText(/Dublin/)).toBeNull();
  expect(screen.queryByRole('group', {name: 'Theme'})).toBeNull();
  expect(screen.queryByRole('dialog', {name: 'Settings'})).toBeNull();

  fireEvent.pointerDown(screen.getByText('Workspace content'));
  expect(screen.queryByRole('menuitem', {name: 'Appearance'})).toBeNull();
});

it('opens the Settings dialog and switches sections', async () => {
  renderLayout();

  fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
  fireEvent.click(screen.getByRole('menuitem', {name: 'Appearance'}));

  expect(
    await screen.findByRole('dialog', {name: 'Settings'}),
  ).toBeInTheDocument();
  // The menu popover is dismissed once the dialog opens.
  expect(screen.queryByRole('menuitem', {name: 'Appearance'})).toBeNull();

  expect(screen.getByRole('group', {name: 'Theme'})).toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Dark'})).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  fireEvent.click(screen.getByRole('button', {name: 'Light'}));
  expect(document.documentElement.dataset.theme).toBe('light');
  expect(screen.getByRole('button', {name: 'Light'})).toHaveAttribute(
    'aria-pressed',
    'true',
  );

  fireEvent.click(screen.getByRole('button', {name: 'Model'}));
  const input = screen.getByLabelText('DeepSeek API key');
  fireEvent.change(input, {target: {value: 'sk-test-123'}});
  fireEvent.keyDown(input, {key: 'Enter'});
  expect(window.localStorage.getItem('cosci-api-key')).toBe('sk-test-123');
  // Saving says nothing: the field holds the value it just stored, and a
  // toast repeating that only covered the page it was confirming.
  expect(screen.queryByText('Settings saved')).toBeNull();

  fireEvent.click(screen.getByRole('button', {name: 'Help'}));
  // The Help section renders project info plus the FAQ accordion rows
  // (native <details>, one per question).
  expect(screen.getByText('What is Co-Scientist?')).toBeInTheDocument();
  expect(screen.getByText('Where does my API key go?')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', {name: 'Close settings'}));
  expect(screen.queryByRole('dialog', {name: 'Settings'})).toBeNull();
});

it('persists the BYOK provider choice in the Model section', async () => {
  renderLayout();

  fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
  fireEvent.click(screen.getByRole('menuitem', {name: 'Model'}));
  await screen.findByRole('dialog', {name: 'Settings'});

  // The key label follows the chosen provider; deepseek is the default.
  expect(screen.getByLabelText('DeepSeek API key')).toBeInTheDocument();

  // The chooser is our own menu, not a native select: nothing is in the DOM
  // to pick from until the trigger opens it.
  const trigger = screen.getByRole('button', {name: 'Provider'});
  expect(screen.queryByRole('menuitemradio', {name: 'OpenAI'})).toBeNull();
  fireEvent.click(trigger);

  // Azure is deliberately not offered (see BYOK_PROVIDERS).
  expect(screen.queryByRole('menuitemradio', {name: 'Azure'})).toBeNull();
  expect(screen.getByRole('menuitemradio', {name: 'DeepSeek'})).toHaveAttribute(
    'aria-checked',
    'true',
  );

  fireEvent.click(screen.getByRole('menuitemradio', {name: 'OpenAI'}));
  expect(window.localStorage.getItem('cosci-api-provider')).toBe('openai');
  expect(screen.getByLabelText('OpenAI API key')).toBeInTheDocument();
  expect(screen.queryByText('Settings saved')).toBeNull();
  // Choosing closes the menu.
  expect(screen.queryByRole('menuitemradio', {name: 'OpenAI'})).toBeNull();
});

it('closes the provider menu on Escape without closing Settings', async () => {
  renderLayout();

  fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
  fireEvent.click(screen.getByRole('menuitem', {name: 'Model'}));
  const dialog = await screen.findByRole('dialog', {name: 'Settings'});

  fireEvent.click(screen.getByRole('button', {name: 'Provider'}));
  const option = screen.getByRole('menuitemradio', {name: 'OpenAI'});
  fireEvent.keyDown(option, {key: 'Escape'});

  expect(screen.queryByRole('menuitemradio', {name: 'OpenAI'})).toBeNull();
  expect(dialog).toBeInTheDocument();
});
