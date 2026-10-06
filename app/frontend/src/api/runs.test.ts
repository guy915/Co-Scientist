import {jsonResponse, errorResponse, fetchMock} from '@/http_test_support';
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
  setStoredApiKey,
  setStoredModel,
} from '@/lib/client_id';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
  cancelRun,
  createInterview,
  createRun,
  exchangeAccessCode,
  getEvidence,
  getHypotheses,
  getMatches,
  getReport,
  getReviews,
  getRun,
  listDemoRuns,
  listRuns,
  loadRunHistory,
  startRun,
} from './runs';

// VITE_API_BASE_URL is captured at import; unset values produce relative URLs.
function firstCall(): [string, RequestInit | undefined] {
  return fetchMock().mock.calls[0] as [string, RequestInit | undefined];
}

function sentHeaders(): Record<string, string> {
  return firstCall()[1]?.headers as Record<string, string>;
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  clearAccessToken();
  localStorage.clear();
});

describe('runs api', () => {
  it('creates a run with a JSON body, the client id and an optional idempotency key', async () => {
    fetchMock().mockResolvedValue(jsonResponse({id: 'r1'}));
    const payload = {
      research_goal: 'g',
      interview_id: 'chat-1',
      document_ids: ['doc-1'],
    };

    await createRun(payload, {idempotencyKey: 'create-key-1'});
    await createRun({research_goal: 'g'});

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs');
    expect(opts?.method).toBe('POST');
    expect(opts?.body).toBe(JSON.stringify(payload));
    expect(sentHeaders()['Content-Type']).toBe('application/json');
    expect(sentHeaders()['X-Client-ID']).toBeTruthy();
    expect(sentHeaders()['Idempotency-Key']).toBe('create-key-1');
    const second = fetchMock().mock.calls[1][1] as RequestInit;
    expect(
      (second.headers as Record<string, string>)['Idempotency-Key'],
    ).toBeUndefined();
  });

  it.each([
    ['listRuns', () => listRuns(), 'runs', '/api/runs'],
    [
      'listRuns with a limit',
      () => listRuns(1000),
      'runs',
      '/api/runs?limit=1000',
    ],
    ['listDemoRuns', () => listDemoRuns(), 'runs', '/api/runs/demo'],
    [
      'getHypotheses',
      () => getHypotheses('r1'),
      'hypotheses',
      '/api/runs/r1/hypotheses',
    ],
    [
      'getEvidence',
      () => getEvidence('r1'),
      'evidence',
      '/api/runs/r1/evidence',
    ],
    ['getMatches', () => getMatches('r1'), 'matches', '/api/runs/r1/matches'],
    ['getReviews', () => getReviews('r1'), 'reviews', '/api/runs/r1/reviews'],
  ])('%s unwraps its keyed payload', async (_name, call, key, url) => {
    fetchMock().mockResolvedValue(jsonResponse({[key]: [{id: 'a'}]}));

    expect(await call()).toEqual([{id: 'a'}]);

    expect(firstCall()[0]).toBe(url);
  });

  it.each([
    ['demo', '/demo', 'owned'],
    ['owned', '/runs', 'demo-1'],
  ])(
    'degrades a failing %s source without blocking the other',
    async (_name, failing, survivor) => {
      fetchMock().mockImplementation((url: string) => {
        const isDemo = url.includes('/demo');
        if (isDemo === (failing === '/demo')) {
          return Promise.reject(new TypeError('Failed to fetch'));
        }
        return Promise.resolve(
          jsonResponse({runs: [{id: survivor, updated_at: 10}]}),
        );
      });

      expect(await loadRunHistory()).toEqual([{id: survivor, updated_at: 10}]);
    },
  );

  it('returns null for a missing report and throws on other failures', async () => {
    fetchMock().mockResolvedValueOnce(errorResponse(404, 'not found'));
    expect(await getReport('r1')).toBeNull();

    fetchMock().mockResolvedValueOnce(errorResponse(500, 'boom'));
    await expect(getReport('r1')).rejects.toThrow('500 boom');
  });

  it('reads one run and starts it with owner data', async () => {
    fetchMock().mockResolvedValue(jsonResponse({id: 'r7', status: 'queued'}));

    await getRun('r7');
    await startRun('r7');

    const [read, started] = fetchMock().mock.calls as [string, RequestInit][];
    expect(read[0]).toBe('/api/runs/r7');
    expect(started[0]).toBe('/api/runs/r7/start');
    expect(started[1].method).toBe('POST');
    expect(JSON.parse(started[1].body as string)).toEqual({});
    expect(
      (started[1].headers as Record<string, string>)['X-Client-ID'],
    ).toBeTruthy();
  });

  it('cancels a run with a POST to its cancel route', async () => {
    fetchMock().mockResolvedValue(
      jsonResponse({id: 'r1', status: 'cancelled'}),
    );

    expect(await cancelRun('r1')).toEqual({id: 'r1', status: 'cancelled'});

    const [url, opts] = firstCall();
    expect(url).toBe('/api/runs/r1/cancel');
    expect(opts?.method).toBe('POST');
  });

  it('merges owned and demo runs de-duped with demo winning, newest first', async () => {
    fetchMock().mockImplementation((url: string) =>
      Promise.resolve(
        jsonResponse(
          url.includes('/demo')
            ? {
                runs: [
                  {id: 'shared', updated_at: 99},
                  {id: 'other', updated_at: 50},
                ],
              }
            : {runs: [{id: 'shared', updated_at: 1}]},
        ),
      ),
    );

    const result = await loadRunHistory();

    expect(result.map(run => run.id)).toEqual(['shared', 'other']);
    expect(result[0].updated_at).toBe(99);
  });
});

describe('error messages', () => {
  it.each([
    ['status and body', errorResponse(500, 'kaboom'), '500 kaboom'],
    ['an empty body', errorResponse(500, ''), 'API unavailable'],
    [
      'statusText when the body cannot be read',
      {
        ok: false,
        status: 502,
        statusText: 'Bad Gateway',
        json: async () => ({}),
        text: () => Promise.reject(new Error('stream closed')),
      } as unknown as Response,
      '502 Bad Gateway',
    ],
    [
      'a free-usage refusal as the server wrote it',
      errorResponse(429, JSON.stringify({detail: 'You used your free runs.'})),
      /^You used your free runs\.$/,
    ],
  ])('reports %s', async (_name, response, expected) => {
    fetchMock().mockResolvedValue(response);
    await expect(getRun('r1')).rejects.toThrow(expected);
  });

  it('does not replace network failures with offline sample runs', async () => {
    fetchMock().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(listRuns()).rejects.toThrow('Failed to fetch');
  });
});

describe('BYOK headers', () => {
  async function headersAfterCreate() {
    fetchMock().mockResolvedValue(jsonResponse({id: 'r1'}));
    await createRun({research_goal: 'g'});
    return sentHeaders();
  }

  it('sends no BYOK headers without a stored key, even with a chosen model', async () => {
    localStorage.setItem('cosci-api-model', 'deepseek/deepseek-v4-pro');

    const headers = await headersAfterCreate();

    expect(headers['X-LLM-API-Key']).toBeUndefined();
    expect(headers['X-LLM-Provider']).toBeUndefined();
    expect(headers['X-LLM-Model']).toBeUndefined();
  });

  describe('keys for several providers', () => {
    beforeEach(() => {
      setStoredApiKey('sk-deepseek', 'deepseek');
      setStoredApiKey('sk-gemini', 'gemini');
    });

    it('sends a supervisor on another provider with its own key', async () => {
      setStoredModel('worker', {
        provider: 'deepseek',
        model: 'deepseek/deepseek-flash',
      });
      setStoredModel('supervisor', {
        provider: 'gemini',
        model: 'gemini/gemini-3.1-pro-preview',
      });

      const headers = await headersAfterCreate();

      expect(headers['X-LLM-Provider']).toBe('deepseek');
      expect(headers['X-LLM-API-Key']).toBe('sk-deepseek');
      expect(headers['X-LLM-Supervisor-Provider']).toBe('gemini');
      expect(headers['X-LLM-Supervisor-API-Key']).toBe('sk-gemini');
      expect(headers['X-LLM-Supervisor-Model']).toBe(
        'gemini/gemini-3.1-pro-preview',
      );
    });
  });
});

describe('researcher session expiry', () => {
  function pendingResponse() {
    let respond!: (response: Response) => void;
    fetchMock().mockReturnValue(
      new Promise<Response>(resolve => {
        respond = resolve;
      }),
    );
    return (response: Response) => respond(response);
  }

  it.each([
    ['JSON', () => getRun('r1')],
    ['streaming', () => createInterview('a goal')],
  ])('clears the token when a %s request returns 401', async (_kind, call) => {
    setAccessToken('expired-token');
    fetchMock().mockResolvedValue(errorResponse(401, 'token expired'));

    await expect(call()).rejects.toThrow('401');

    expect(getAccessToken()).toBeNull();
  });

  it('keeps the token on a non-401 error', async () => {
    setAccessToken('good-token');
    fetchMock().mockResolvedValue(errorResponse(500, 'server error'));

    await expect(getRun('r1')).rejects.toThrow('500');

    expect(getAccessToken()).toBe('good-token');
  });

  it('keeps a new session when an anonymous background request returns 401', async () => {
    const respond = pendingResponse();
    const pending = listDemoRuns();
    setAccessToken('new-session');
    respond(errorResponse(401, 'researcher access required'));
    await expect(pending).rejects.toThrow('401');
    expect(getAccessToken()).toBe('new-session');
  });

  it.each([
    ['JSON', () => getRun('r1')],
    ['streaming', () => createInterview('a goal')],
  ])(
    'keeps a replacement session when an old %s request returns 401',
    async (_kind, call) => {
      const respond = pendingResponse();
      setAccessToken('old-session');
      const pending = call();
      setAccessToken('replacement-session');
      respond(errorResponse(401, 'token expired'));
      await expect(pending).rejects.toThrow('401');
      expect(getAccessToken()).toBe('replacement-session');
    },
  );

  it('keeps a session when an access-code exchange is refused', async () => {
    setAccessToken('valid-session');
    fetchMock().mockResolvedValue(errorResponse(401, 'invalid access code'));
    await expect(exchangeAccessCode('wrong-invite')).rejects.toThrow('401');
    expect(getAccessToken()).toBe('valid-session');
  });
});
