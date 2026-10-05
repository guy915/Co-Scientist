import {makeRunMessage} from '@/test_fixtures';
import {FakeSseBody, streamingResponse, fetchMock} from '@/http_test_support';
import {beforeEach, afterEach, describe, expect, it, vi} from 'vitest';
import {
  askRunQuestion,
  getRunMessages,
  type QaSource,
  announceRunStart,
} from './runs';

describe('runs qa', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const SOURCE: QaSource = {
    n: 1,
    evidence_id: 'ev-1',
    title: 'A supporting paper',
    state: 'verified',
  };

  describe('askRunQuestion', () => {
    it('relays sources and chunks as they stream, then resolves the question id', async () => {
      const body = new FakeSseBody();
      fetchMock().mockResolvedValue(streamingResponse(body));
      const onSources = vi.fn();
      const onChunk = vi.fn();

      const pending = askRunQuestion('run-1', 'Why?', {onSources, onChunk});
      body.push({type: 'sources', sources: [SOURCE]});
      body.push({type: 'chunk', content: 'Because '});
      body.push({type: 'chunk', content: 'evidence.'});
      body.push({type: 'done', question_id: 42});
      body.end();

      await expect(pending).resolves.toBe(42);
      expect(onSources).toHaveBeenCalledWith([SOURCE]);
      expect(onChunk).toHaveBeenNthCalledWith(1, 'Because ');
      expect(onChunk).toHaveBeenNthCalledWith(2, 'evidence.');
    });

    it('throws on an error frame instead of resolving', async () => {
      const body = new FakeSseBody();
      fetchMock().mockResolvedValue(streamingResponse(body));

      const pending = askRunQuestion('run-1', 'Why?');
      body.push({type: 'error', message: 'no model configured'});
      body.end();

      await expect(pending).rejects.toThrow('no model configured');
    });

    it('aborts the underlying fetch when the signal fires', async () => {
      fetchMock().mockImplementation(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => {
              reject(new DOMException('aborted', 'AbortError'));
            });
          }),
      );
      const controller = new AbortController();

      const pending = askRunQuestion('run-1', 'Why?', {}, controller.signal);
      controller.abort();

      await expect(pending).rejects.toMatchObject({name: 'AbortError'});
    });
  });

  describe('getRunMessages', () => {
    it('unwraps the messages envelope', async () => {
      fetchMock().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          messages: [makeRunMessage({content: 'Why?', applied: true})],
        }),
        text: async () => '',
      });

      const messages = await getRunMessages('run-1');

      expect(messages).toHaveLength(1);
      expect(messages[0].content).toBe('Why?');
    });
  });
});

describe('runs start', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('relays reasoning and prose, then resolves what done reports', async () => {
    const body = new FakeSseBody();
    fetchMock().mockResolvedValue(streamingResponse(body));
    const reasoning: string[] = [];
    const chunks: string[] = [];

    const pending = announceRunStart('run-1', 'Start research', {
      onReasoning: fragment => reasoning.push(fragment),
      onChunk: fragment => chunks.push(fragment),
    });
    body.push({type: 'reasoning', content: 'The run exists.'});
    body.push({type: 'chunk', content: 'Your session '});
    body.push({type: 'chunk', content: 'is under way.'});
    body.push({type: 'done', prompt_id: 8, fallback: false});
    body.end();

    expect(await pending).toEqual({fallback: false});
    expect(reasoning).toEqual(['The run exists.']);
    expect(chunks.join('')).toBe('Your session is under way.');
  });

  it('posts the scientist prompt to the run that was started', async () => {
    const body = new FakeSseBody();
    fetchMock().mockResolvedValue(streamingResponse(body));

    const pending = announceRunStart('run-7', 'Start research');
    body.push({type: 'done', prompt_id: 1, fallback: true});
    body.end();
    await pending;

    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/runs\/run-7\/messages\/started$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({prompt: 'Start research'});
  });

  it('reports the fallback the server settled on', async () => {
    const body = new FakeSseBody();
    fetchMock().mockResolvedValue(streamingResponse(body));

    const pending = announceRunStart('run-1', 'Start research');
    body.push({type: 'chunk', content: 'Standby copy.'});
    body.push({type: 'done', prompt_id: 2, fallback: true});
    body.end();

    expect(await pending).toEqual({fallback: true});
  });
});
