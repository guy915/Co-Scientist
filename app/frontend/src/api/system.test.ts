import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {getSystemStatus, type SystemStatus} from './system';

/** A representative /status payload for the offline mock configuration. */
const STATUS: SystemStatus = {
  mcp_available: false,
  pubmed_available: false,
  literature_review_available: false,
  probes: {
    mcp: {state: 'down', error: null},
    pubmed: {state: 'error', error: 'probe timed out after 3s'},
  },
  mcp_server_url: 'http://localhost:8888/mcp',
  provider: 'engine',
  mock_mode: true,
  llm_backend: 'offline',
  has_provider_key: false,
  engine_importable: true,
  model_name: 'gemini/gemini-2.5-flash',
  supervisor_model_name: 'gemini/gemini-2.5-flash',
  connectors: [{id: 'pubmed', display: 'PubMed'}],
};

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('getSystemStatus', () => {
  it('fetches /status and returns the parsed payload', async () => {
    const mock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    mock.mockResolvedValue(jsonResponse(STATUS));

    const status = await getSystemStatus();

    expect(mock.mock.calls[0][0]).toBe('/status');
    expect(status.mock_mode).toBe(true);
    expect(status.probes.pubmed.state).toBe('error');
  });

  it('throws a descriptive error on a non-OK response', async () => {
    const mock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    mock.mockResolvedValue({
      ok: false,
      status: 502,
      statusText: 'Bad Gateway',
      text: async () => 'upstream down',
    } as unknown as Response);

    await expect(getSystemStatus()).rejects.toThrow('502 upstream down');
  });
});
