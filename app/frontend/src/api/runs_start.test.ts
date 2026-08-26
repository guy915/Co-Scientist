// announceRunStart streams the Agent's reply to "Start research" through its
// two sinks and resolves what the terminal `done` frame reports. Mirrors the
// SSE test harness in runs_qa.test.ts.

import {beforeEach, afterEach, expect, it, vi} from 'vitest';
import {announceRunStart} from './runs_start';

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
