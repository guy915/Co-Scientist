import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {
  type ByokProvider,
  getStoredApiKey,
  getStoredModel,
  setStoredApiKey,
} from '@/lib/client_id';
import {ThemeProvider} from '../theme_context';
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

function renderDialog(onClose = vi.fn()) {
  return render(
    <ThemeProvider>
      <SettingsDialog
        section="model"
        onSectionChange={vi.fn()}
        onClose={onClose}
      />
    </ThemeProvider>,
  );
}

function trigger(name: RegExp | string) {
  return screen.getByRole('button', {name});
}

it('shows supervisor and worker selects on the provider defaults', async () => {
  renderSection('sk-key', 'deepseek');
  expect(await screen.findAllByText('deepseek-flash')).toHaveLength(2);
  expect(trigger(/Supervisor model/)).toBeEnabled();
  expect(trigger(/Worker model/)).toBeEnabled();
});

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

it('offers the models of every provider with a saved key, grouped', async () => {
  const user = userEvent.setup();
  renderSection('sk-d', 'deepseek', ['deepseek', 'gemini']);
  await screen.findAllByText('deepseek-flash');
  await user.click(trigger(/Supervisor model/));
  const menu = screen.getByRole('menu', {name: 'Supervisor model'});
  const deepseek = within(menu).getByRole('group', {name: 'DeepSeek'});
  const gemini = within(menu).getByRole('group', {name: 'Gemini'});
  expect(within(deepseek).getAllByRole('menuitemradio')).toHaveLength(2);
  expect(within(menu).queryByRole('group', {name: 'OpenAI'})).toBeNull();

  await user.click(
    within(gemini).getByRole('menuitemradio', {name: 'gemini-3.1-pro-preview'}),
  );
  expect(getStoredModel('supervisor')).toEqual({
    provider: 'gemini',
    model: 'gemini/gemini-3.1-pro-preview',
  });
  expect(getStoredModel('worker')).toEqual({
    provider: 'deepseek',
    model: 'deepseek/deepseek-flash',
  });
});

it('removes only the cleared provider key from the model lists', async () => {
  const user = userEvent.setup();
  setStoredApiKey('sk-deepseek', 'deepseek');
  setStoredApiKey('sk-gemini', 'gemini');
  renderDialog();
  await screen.findAllByText('deepseek-flash');
  await user.click(trigger(/^Provider/));
  await user.click(screen.getByRole('menuitemradio', {name: /Gemini/}));
  await user.clear(screen.getByLabelText('Gemini API key'));
  await user.tab();

  expect(getStoredApiKey('gemini')).toBe('');
  expect(getStoredApiKey('deepseek')).toBe('sk-deepseek');
  await user.click(trigger(/Worker model/));
  const menu = screen.getByRole('menu', {name: 'Worker model'});
  expect(within(menu).queryByText('gemini-3.8-flash')).toBeNull();
  expect(within(menu).getByText('deepseek-flash')).toBeInTheDocument();
});
