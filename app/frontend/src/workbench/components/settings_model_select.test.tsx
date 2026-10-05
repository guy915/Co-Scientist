import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {
  type ByokProvider,
  getStoredApiKey,
  getStoredModel,
  setStoredApiKey,
  setStoredApiProvider,
  setStoredModel,
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

it('keeps both selects choosable and explains free usage without a key', async () => {
  renderSection('', 'deepseek');
  expect(
    await screen.findByText(/2 of 3 free runs left today/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Only Express runs/)).toBeInTheDocument();
  expect(await screen.findAllByText('deepseek-flash')).toHaveLength(2);
  expect(trigger(/Supervisor model/)).toBeEnabled();
  expect(trigger(/Worker model/)).toBeEnabled();
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

it('keeps the shown supervisor when the worker moves provider', async () => {
  const user = userEvent.setup();
  renderSection('sk-d', 'deepseek', ['deepseek', 'gemini']);
  await screen.findAllByText('deepseek-flash');
  await user.click(trigger(/Worker model/));
  const menu = screen.getByRole('menu', {name: 'Worker model'});
  await user.click(
    within(menu).getByRole('menuitemradio', {name: 'gemini-3.8-flash'}),
  );
  expect(trigger(/Supervisor model/)).toHaveTextContent('deepseek-flash');
});

it('shows each provider its own saved key and marks the keyed ones', async () => {
  const user = userEvent.setup();
  setStoredApiKey('sk-gemini', 'gemini');
  setStoredApiKey('sk-openai', 'openai');
  renderDialog();
  const key = () => screen.getByPlaceholderText(/API key/);
  expect(key()).toHaveValue('');

  await user.click(trigger('Provider'));
  const menu = screen.getByRole('menu', {name: 'Provider'});
  expect(within(menu).getAllByText('Saved')).toHaveLength(2);
  await user.click(within(menu).getByRole('menuitemradio', {name: /Gemini/}));
  expect(key()).toHaveValue('sk-gemini');

  await user.click(trigger('Provider'));
  await user.click(screen.getByRole('menuitemradio', {name: /OpenAI/}));
  expect(key()).toHaveValue('sk-openai');
});

it('removes only the cleared provider key from the model lists', async () => {
  const user = userEvent.setup();
  setStoredApiKey('sk-deepseek', 'deepseek');
  setStoredApiKey('sk-gemini', 'gemini');
  renderDialog();
  await screen.findAllByText('deepseek-flash');
  await user.click(trigger('Provider'));
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

it('drops a stored model the catalog no longer offers', async () => {
  setStoredApiKey('sk-deepseek');
  setStoredModel('worker', {
    provider: 'deepseek',
    model: 'deepseek/deepseek-v4-flash',
  });
  renderDialog();
  await screen.findAllByText('deepseek-flash');
  expect(getStoredModel('worker')).toBeNull();
});

it('keeps model choices when the viewed provider changes', () => {
  setStoredModel('worker', {
    provider: 'deepseek',
    model: 'deepseek/deepseek-v4-pro',
  });
  setStoredApiProvider('openai');
  expect(getStoredModel('worker')?.model).toBe('deepseek/deepseek-v4-pro');
});

it.each(['Provider', 'Supervisor model', 'Worker model'])(
  '%s dismisses its menu without closing the settings dialog',
  async name => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderDialog(onClose);
    await screen.findAllByText('deepseek-flash');
    const chooser = screen.getByRole('button', {name});

    await user.click(chooser);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu', {name})).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    await user.click(chooser);
    const selected = within(screen.getByRole('menu', {name})).getByRole(
      'menuitemradio',
      {checked: true},
    );
    await user.click(selected);
    expect(screen.queryByRole('menu', {name})).not.toBeInTheDocument();
    expect(getStoredModel('worker')).toBeNull();
    expect(getStoredModel('supervisor')).toBeNull();

    await user.click(chooser);
    await user.click(screen.getByLabelText('DeepSeek API key'));
    expect(screen.queryByRole('menu', {name})).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  },
);

it('keeps API keys and model choices in separate boxes', async () => {
  renderSection('sk-key', 'deepseek');
  const keys = screen.getByRole('region', {name: 'API keys'});
  const models = screen.getByRole('region', {name: 'Models'});
  expect(within(keys).getByRole('button', {name: /Provider/})).toBeTruthy();
  expect(within(keys).queryByRole('button', {name: /Worker model/})).toBeNull();
  expect(
    await within(models).findByRole('button', {name: /Worker model/}),
  ).toBeTruthy();
});
