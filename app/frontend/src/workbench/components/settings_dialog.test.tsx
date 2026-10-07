import {render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {useState} from 'react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {type ByokProvider, getStoredModel} from '@/shared/lib/client_id';
import {ThemeProvider} from '@/shared/hooks/theme_context';
import {ModelSection, SettingsDialog} from './settings_dialog';

const CATALOG = {
  deepseek: ['deepseek/deepseek-flash', 'deepseek/deepseek-v4-pro'],
  gemini: ['gemini/gemini-3.8-flash', 'gemini/gemini-3.1-pro-preview'],
  openai: ['openai/gpt-6.1-sol', 'openai/gpt-6-luna'],
};

const FREE_USAGE = {
  enforced: true,
  tier: 'express',
  limit: 3,
  used: 1,
  remaining: 2,
  resets_at: 0,
};

function respond(body: unknown): Response {
  return {ok: true, status: 200, json: async () => body} as Response;
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      respond(
        url.endsWith('/api/byok-models') ? {providers: CATALOG} : FREE_USAGE,
      ),
    ),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

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

function renderSection(
  apiKey: string,
  provider: ByokProvider,
  savedProviders: ByokProvider[] = apiKey ? [provider] : [],
) {
  return render(
    <ModelSection
      apiKey={apiKey}
      onApiKeyChange={vi.fn()}
      provider={provider}
      onProviderChange={vi.fn()}
      onSave={vi.fn()}
      savedProviders={savedProviders}
    />,
  );
}

function trigger(name: RegExp | string) {
  return screen.getByRole('button', {name});
}

it('stores a chosen supervisor model with its provider', async () => {
  const user = userEvent.setup();
  renderSection('sk-key', 'deepseek');
  await screen.findAllByText('deepseek-flash');
  await user.click(trigger(/Supervisor model/));
  const menu = screen.getByRole('menu', {name: 'Supervisor model'});
  await user.click(
    within(menu).getByRole('menuitemradio', {name: 'deepseek-v4-pro'}),
  );
  expect(getStoredModel('supervisor')).toEqual({
    provider: 'deepseek',
    model: 'deepseek/deepseek-v4-pro',
  });
  expect(getStoredModel('worker')).toEqual({
    provider: 'deepseek',
    model: 'deepseek/deepseek-flash',
  });
});
