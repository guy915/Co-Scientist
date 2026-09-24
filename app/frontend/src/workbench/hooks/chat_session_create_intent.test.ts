import {beforeEach, describe, expect, it, vi} from 'vitest';
import {setStoredApiKey, setStoredApiProvider} from '@/lib/api_key';
import {clearAccessToken, setAccessToken} from '@/lib/client_id';
import {getPendingCreateIntent} from './chat_session_create_intent';

const PAYLOAD = {
  research_goal: 'map the pathway',
  interview_id: 'chat-1',
  requirements: ['human cells'],
  document_ids: ['doc-1'],
};

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

describe('pending create intent', () => {
  it('reuses the same key and exact payload after the helper is reloaded', async () => {
    setAccessToken('bearer-secret-one');
    setStoredApiKey('sk-secret-one');
    setStoredApiProvider('openai');
    const first = await getPendingCreateIntent('chat-1', PAYLOAD);
    const storedRecord = sessionStorage.getItem(
      'co_scientist_pending_run_create:chat-1',
    );

    vi.resetModules();
    const {getPendingCreateIntent: afterReload} =
      await import('./chat_session_create_intent');
    const second = await afterReload('chat-1', PAYLOAD);

    expect(second.key).toBe(first.key);
    expect(JSON.stringify(second.payload)).toBe(JSON.stringify(PAYLOAD));
    expect(storedRecord).not.toContain('bearer-secret-one');
    expect(storedRecord).not.toContain('sk-secret-one');
    expect(
      sessionStorage.getItem('co_scientist_pending_run_create:chat-1'),
    ).not.toContain('bearer-secret-one');
  });

  it('rotates the key when the owner changes', async () => {
    setAccessToken('bearer-secret-one');
    const first = await getPendingCreateIntent('chat-1', PAYLOAD);
    setAccessToken('bearer-secret-two');

    const second = await getPendingCreateIntent('chat-1', PAYLOAD);

    expect(second.key).not.toBe(first.key);
    expect(
      sessionStorage.getItem('co_scientist_pending_run_create:chat-1'),
    ).not.toContain('bearer-secret-two');
  });

  it('rotates the key when auth falls back from bearer to client id', async () => {
    setAccessToken('bearer-secret');
    const authenticated = await getPendingCreateIntent('chat-1', PAYLOAD);
    clearAccessToken();

    const clientOwned = await getPendingCreateIntent('chat-1', PAYLOAD);

    expect(clientOwned.key).not.toBe(authenticated.key);
  });

  it('rotates the key when the create payload changes', async () => {
    const first = await getPendingCreateIntent('chat-1', PAYLOAD);

    const second = await getPendingCreateIntent('chat-1', {
      ...PAYLOAD,
      research_goal: 'a different goal',
    });

    expect(second.key).not.toBe(first.key);
    expect(second.payload.research_goal).toBe('a different goal');
  });

  it('rotates the key when the explicit BYOK credential changes', async () => {
    setStoredApiKey('sk-secret-one');
    setStoredApiProvider('openai');
    const first = await getPendingCreateIntent('chat-1', PAYLOAD);
    setStoredApiKey('sk-secret-two');

    const second = await getPendingCreateIntent('chat-1', PAYLOAD);

    expect(second.key).not.toBe(first.key);
    const stored = sessionStorage.getItem(
      'co_scientist_pending_run_create:chat-1',
    );
    expect(stored).not.toContain('sk-secret-one');
    expect(stored).not.toContain('sk-secret-two');
  });

  it('rotates the key when the BYOK provider changes', async () => {
    setStoredApiKey('sk-secret');
    setStoredApiProvider('openai');
    const first = await getPendingCreateIntent('chat-1', PAYLOAD);
    setStoredApiProvider('anthropic');

    const second = await getPendingCreateIntent('chat-1', PAYLOAD);

    expect(second.key).not.toBe(first.key);
  });
});
