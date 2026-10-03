import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {getStoredModel, setStoredApiProvider} from '@/lib/api_key';
import {ModelSection} from './settings_dialog';

const CATALOG = {
  deepseek: ['deepseek/deepseek-v4-flash', 'deepseek/deepseek-v4-pro'],
  openai: ['openai/gpt-4o', 'openai/gpt-4o-mini'],
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

function renderSection(apiKey: string, provider: 'deepseek' | 'openai') {
  return render(
    <ModelSection
      apiKey={apiKey}
      onApiKeyChange={vi.fn()}
      provider={provider}
      onProviderChange={vi.fn()}
      onSave={vi.fn()}
    />,
  );
}

function trigger(name: RegExp) {
  return screen.getByRole('button', {name});
}

it('shows supervisor and worker selects on the provider defaults', async () => {
  renderSection('sk-key', 'deepseek');
  expect(await screen.findAllByText('deepseek-v4-flash')).toHaveLength(2);
  expect(trigger(/Supervisor model/)).toBeEnabled();
  expect(trigger(/Worker model/)).toBeEnabled();
});

it('stores a chosen supervisor model', async () => {
  const user = userEvent.setup();
  renderSection('sk-key', 'deepseek');
  await screen.findAllByText('deepseek-v4-flash');
  await user.click(trigger(/Supervisor model/));
  const menu = screen.getByRole('menu', {name: 'Supervisor model'});
  await user.click(
    within(menu).getByRole('menuitemradio', {name: 'deepseek-v4-pro'}),
  );
  expect(getStoredModel('supervisor')).toBe('deepseek/deepseek-v4-pro');
  expect(getStoredModel('worker')).toBe('');
});

it('keeps both selects choosable and explains free usage without a key', async () => {
  renderSection('', 'deepseek');
  expect(
    await screen.findByText(/2 of 3 free runs left today/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Only Express runs/)).toBeInTheDocument();
  expect(await screen.findAllByText('deepseek-v4-flash')).toHaveLength(2);
  expect(trigger(/Supervisor model/)).toBeEnabled();
  expect(trigger(/Worker model/)).toBeEnabled();
});

it('resets model choices when the provider changes', () => {
  setStoredApiProvider('deepseek');
  window.localStorage.setItem('cosci-api-model', 'deepseek/deepseek-v4-pro');
  setStoredApiProvider('openai');
  expect(getStoredModel('worker')).toBe('');
});
