import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {DataRightsSection} from './data_rights_section';
import {STORAGE_KEYS} from '@/shared/lib/safe_storage';

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

it('requires exact confirmation and keeps private storage after a failed deletion', async () => {
  const user = userEvent.setup();
  localStorage.setItem(STORAGE_KEYS.clientId, 'synthetic-owner');
  localStorage.setItem(STORAGE_KEYS.apiKeys, 'synthetic-credential');
  const fetch = vi.fn(
    async () =>
      new Response(JSON.stringify({detail: 'Deletion unavailable'}), {
        status: 503,
        headers: {'Content-Type': 'application/json'},
      }),
  );
  vi.stubGlobal('fetch', fetch);
  render(
    <MemoryRouter>
      <DataRightsSection onOpenLegal={() => {}} />
    </MemoryRouter>,
  );
  const button = screen.getByRole('button', {name: 'Delete all my data'});
  expect(button).toBeDisabled();
  await user.type(screen.getByLabelText('Type DELETE to confirm'), 'delete');
  expect(button).toBeDisabled();
  expect(fetch).not.toHaveBeenCalled();
  await user.clear(screen.getByLabelText('Type DELETE to confirm'));
  await user.type(screen.getByLabelText('Type DELETE to confirm'), 'DELETE');
  await user.click(button);
  await waitFor(() =>
    expect(screen.getByRole('status')).toHaveTextContent(
      'Deletion unavailable',
    ),
  );
  expect(localStorage.getItem(STORAGE_KEYS.apiKeys)).toBe(
    'synthetic-credential',
  );
  expect(localStorage.getItem(STORAGE_KEYS.clientId)).toBe('synthetic-owner');
  const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(init.headers).toMatchObject({'X-Client-ID': 'synthetic-owner'});
  expect(JSON.stringify(init)).not.toContain('synthetic-credential');
});

it('closes the settings overlay when opening a legal notice', async () => {
  const user = userEvent.setup();
  const close = vi.fn();
  render(
    <MemoryRouter>
      <DataRightsSection onOpenLegal={close} />
    </MemoryRouter>,
  );
  await user.click(screen.getByRole('link', {name: 'Terms of use'}));
  expect(close).toHaveBeenCalledOnce();
});
