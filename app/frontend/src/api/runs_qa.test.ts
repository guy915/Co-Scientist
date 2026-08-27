// askRunQuestion streams sources/chunk/error frames through QaSinks and
// resolves the persisted question id from `done`; getRunMessages unwraps the
// `messages` envelope. Mirrors the SSE test harness in use_run_stream.test.ts.

import {beforeEach, afterEach, describe, expect, it, vi} from 'vitest';
import {askRunQuestion, getRunMessages, type QaSource} from './runs_qa';

/** A controllable SSE body: tests push frames and the reader consumes them. */
class FakeSseBody {
  private controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  readonly stream = new ReadableStream<Uint8Array>({
    start: c => {
      this.controller = c;
    },
  });
  private readonly encoder = new TextEncoder();

  push(frame: unknown): void {
    this.controller?.enqueue(
      this.encoder.encode(`data: ${JSON.stringify(frame)}\n\n`),
    );
  }

  end(): void {
    this.controller?.close();
  }
}

function streamingResponse(body: FakeSseBody): Response {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    body: body.stream,
    text: async () => '',
  } as unknown as Response;
}

function fetchMock() {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
}

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
        messages: [
          {
            id: 1,
            run_id: 'run-1',
            sender: 'user',
            content: 'Why?',
            kind: 'qa',
            created_at: 1,
            applied: true,
            meta: null,
          },
        ],
      }),
      text: async () => '',
    });

    const messages = await getRunMessages('run-1');

    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe('Why?');
  });
});
