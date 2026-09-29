// Bring-your-own-key transport: the stored key/provider ride along as
// X-LLM-API-Key / X-LLM-Provider request headers on run creation and the
// interview path (never query parameters). The backend validates the pair
// live and stores the key encrypted for the run's lifetime.

import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {createInterview, createRun} from './runs';

/** Builds a minimal Response-like object that resolves the given JSON body. */
function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

/** Builds a Response-like object representing a non-OK HTTP error. */
function errorResponse(status: number, text = 'boom'): Response {
  return {
    ok: false,
    status,
    statusText: 'Error',
    json: async () => ({}),
    text: async () => text,
  } as unknown as Response;
}

/** The mocked global fetch, narrowed to its mock surface. */
function fetchMock() {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
}

/** Returns the [url, options] pair fetch was invoked with on the first call. */
function firstCall(): [string, RequestInit | undefined] {
  return fetchMock().mock.calls[0] as [string, RequestInit | undefined];
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.removeItem('cosci-api-key');
  localStorage.removeItem('cosci-api-provider');
  localStorage.removeItem('cosci-api-model');
  localStorage.removeItem('cosci-api-supervisor-model');
});

describe('createRun BYOK transport', () => {
  it('sends the chosen worker and supervisor models with the key', async () => {
    localStorage.setItem('cosci-api-key', 'sk-byok-1');
    localStorage.setItem('cosci-api-provider', 'deepseek');
    localStorage.setItem('cosci-api-model', 'deepseek/deepseek-v4-flash');
    localStorage.setItem(
      'cosci-api-supervisor-model',
      'deepseek/deepseek-v4-pro',
    );
    fetchMock().mockResolvedValue(jsonResponse({id: 'r1'}));

    await createRun({research_goal: 'g'});

    const headers = firstCall()[1]?.headers as Record<string, string>;
    expect(headers['X-LLM-Model']).toBe('deepseek/deepseek-v4-flash');
    expect(headers['X-LLM-Supervisor-Model']).toBe('deepseek/deepseek-v4-pro');
  });

  it('surfaces a free-usage refusal as the server wrote it', async () => {
    const detail = 'You have used your 3 free runs for today.';
    fetchMock().mockResolvedValue(errorResponse(429, JSON.stringify({detail})));
    await expect(createRun({research_goal: 'g'})).rejects.toThrow(
      new RegExp(`^${detail}$`),
    );
  });

  it('sends no model headers without a key', async () => {
    localStorage.setItem('cosci-api-model', 'deepseek/deepseek-v4-pro');
    fetchMock().mockResolvedValue(jsonResponse({id: 'r1'}));

    await createRun({research_goal: 'g'});

    const headers = firstCall()[1]?.headers as Record<string, string>;
    expect(headers['X-LLM-Model']).toBeUndefined();
  });

  it('sends stored BYOK credentials as request headers', async () => {
    localStorage.setItem('cosci-api-key', 'sk-byok-1');
    localStorage.setItem('cosci-api-provider', 'openai');
    fetchMock().mockResolvedValue(jsonResponse({id: 'r1'}));

    await createRun({research_goal: 'g'});

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs');
    const headers = opts?.headers as Record<string, string>;
    expect(headers['X-LLM-API-Key']).toBe('sk-byok-1');
    expect(headers['X-LLM-Provider']).toBe('openai');
  });

  it('defaults the provider header to deepseek', async () => {
    localStorage.setItem('cosci-api-key', 'sk-byok-1');
    fetchMock().mockResolvedValue(jsonResponse({id: 'r1'}));

    await createRun({research_goal: 'g'});

    const [, opts] = firstCall();
    const headers = opts?.headers as Record<string, string>;
    expect(headers['X-LLM-Provider']).toBe('deepseek');
  });

  it('sends no BYOK headers when no key is stored', async () => {
    fetchMock().mockResolvedValue(jsonResponse({id: 'r1'}));

    await createRun({research_goal: 'g'});

    const [, opts] = firstCall();
    const headers = opts?.headers as Record<string, string>;
    expect(headers['X-LLM-API-Key']).toBeUndefined();
    expect(headers['X-LLM-Provider']).toBeUndefined();
  });
});

describe('interview BYOK transport', () => {
  it('sends stored BYOK credentials on interview turns', async () => {
    localStorage.setItem('cosci-api-key', 'sk-byok-2');
    localStorage.setItem('cosci-api-provider', 'gemini');
    // The error path asserts on the request before any frame is read.
    fetchMock().mockResolvedValue(errorResponse(400, 'rejected'));

    await expect(createInterview('a goal')).rejects.toThrow('400');

    const [url, opts] = firstCall();
    expect(url).toBe('/api/interviews');
    const headers = opts?.headers as Record<string, string>;
    expect(headers['X-LLM-API-Key']).toBe('sk-byok-2');
    expect(headers['X-LLM-Provider']).toBe('gemini');
  });
});
