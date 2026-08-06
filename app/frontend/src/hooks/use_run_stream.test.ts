import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {renderHook, act} from '@testing-library/react';
import {
  useRunStream,
  RECONNECT_DELAY_MS,
  type StreamEvent,
} from './use_run_stream';

/** The mocked global fetch, narrowed to its mock surface. */
function fetchMock() {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
}

/**
 * A controllable SSE body: tests push frames onto it and the hook's
 * `fetch`-based reader (`readSseFrames`) consumes them as they arrive, the
 * same way a real streamed response behaves.
 */
class FakeSseBody {
  private controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  readonly stream = new ReadableStream<Uint8Array>({
    start: c => {
      this.controller = c;
    },
  });
  private readonly encoder = new TextEncoder();

  /** Enqueues one SSE frame carrying the given event as its JSON payload. */
  push(ev: Partial<StreamEvent>): void {
    this.controller?.enqueue(
      this.encoder.encode(`data: ${JSON.stringify(ev)}\n\n`),
    );
  }

  /** Enqueues one raw (non-JSON) SSE frame, to exercise the parse-error path. */
  pushRaw(data: string): void {
    this.controller?.enqueue(this.encoder.encode(`data: ${data}\n\n`));
  }

  /** Ends the stream as the server closing the connection normally. */
  end(): void {
    this.controller?.close();
  }
}

/** Builds a Response-like object streaming from `body`. */
function streamingResponse(body: FakeSseBody): Response {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    body: body.stream,
    text: async () => '',
  } as unknown as Response;
}

/** Builds a Response-like object representing a non-OK HTTP error. */
function errorResponse(status: number): Response {
  return {
    ok: false,
    status,
    statusText: 'Error',
    body: null,
    text: async () => 'boom',
  } as unknown as Response;
}

/**
 * Queues fetch responses in order; a call beyond the queue hangs (mirrors a
 * connection attempt still in flight), which is what a test asserting "no
 * further attempt happened yet" relies on.
 */
function queueFetch(...responses: Response[]): void {
  const queue = [...responses];
  fetchMock().mockImplementation(() => {
    const next = queue.shift();
    return next === undefined
      ? new Promise<Response>(() => {})
      : Promise.resolve(next);
  });
}

/**
 * Advances fake timers by `ms` inside `act`, letting a chained read -> decode
 * -> batch -> flush pipeline settle. Unlike the synchronous `onmessage` a
 * native `EventSource` delivers, each hop here is its own microtask
 * boundary, so `vitest`'s async-aware timer advance (which yields between
 * each timer it fires) is what actually drains the chain rather than a
 * single real `setTimeout(0)`.
 */
async function settle(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('stream setup', () => {
  it('stays idle and opens no stream when runId is null', () => {
    renderHook(() => useRunStream(null));
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it('opens a stream against the run events URL', async () => {
    const body = new FakeSseBody();
    queueFetch(streamingResponse(body));
    renderHook(() => useRunStream('run-1'));
    await settle();

    expect(fetchMock().mock.calls[0][0]).toContain('/api/runs/run-1/events');
  });
});

it('accumulates streamed events and reports the open state', async () => {
  const body = new FakeSseBody();
  queueFetch(streamingResponse(body));
  const {result} = renderHook(() => useRunStream('run-1'));
  await settle();
  expect(result.current.connection).toBe('open');

  body.push({seq: 1, type: 'node_start', payload: {node: 'generate'}});
  body.push({seq: 2, type: 'node_end', payload: {node: 'generate'}});
  await settle();

  expect(result.current.events).toHaveLength(2);
  expect(result.current.events.map(e => e.type)).toEqual([
    'node_start',
    'node_end',
  ]);
});

it('drops replayed events so a reconnect cannot duplicate the timeline', async () => {
  // Every reconnect replays from seq=0, so the same seqs can arrive twice
  // across attempts (or within one, on a burst); dedup keeps the second
  // pass a no-op.
  const body = new FakeSseBody();
  queueFetch(streamingResponse(body));
  const {result} = renderHook(() => useRunStream('run-1'));
  await settle();

  body.push({seq: 1, type: 'a', payload: {}});
  body.push({seq: 2, type: 'b', payload: {}});
  body.push({seq: 1, type: 'a', payload: {}});
  body.push({seq: 2, type: 'b', payload: {}});
  body.push({seq: 3, type: 'c', payload: {}});
  await settle();

  expect(result.current.events.map(e => e.seq)).toEqual([1, 2, 3]);
});

describe('terminal events', () => {
  it('marks terminal and stops the stream on a _terminal event', async () => {
    const body = new FakeSseBody();
    queueFetch(streamingResponse(body));
    const {result} = renderHook(() => useRunStream('run-1'));
    await settle();

    body.push({seq: 1, type: 'node_start', payload: {}});
    body.push({type: '_terminal', payload: {}});
    await settle();

    expect(result.current.terminal).toBe(true);
    // The terminal sentinel itself is not appended to the timeline.
    expect(result.current.events).toHaveLength(1);
    // No further attempt follows a deliberate terminal stop.
    await settle(RECONNECT_DELAY_MS);
    expect(fetchMock().mock.calls).toHaveLength(1);
  });
});

describe('malformed payloads', () => {
  it('does not crash on a malformed frame and reconnects instead', async () => {
    const firstBody = new FakeSseBody();
    const secondBody = new FakeSseBody();
    queueFetch(streamingResponse(firstBody), streamingResponse(secondBody));
    const {result} = renderHook(() => useRunStream('run-1'));
    await settle();

    firstBody.pushRaw('not json{');
    await settle();

    // The bad frame ends that attempt without surfacing a bogus event or
    // throwing out of the hook; the retry timer then opens a new attempt.
    expect(result.current.events).toEqual([]);
    await settle(RECONNECT_DELAY_MS);
    expect(fetchMock().mock.calls.length).toBeGreaterThan(1);
  });
});

it('aborts the in-flight connection on unmount', async () => {
  const body = new FakeSseBody();
  const abortSpy = vi.fn();
  fetchMock().mockImplementation((_url: string, init?: RequestInit) => {
    init?.signal?.addEventListener('abort', abortSpy);
    return Promise.resolve(streamingResponse(body));
  });
  const {unmount} = renderHook(() => useRunStream('run-1'));
  await settle();

  unmount();

  expect(abortSpy).toHaveBeenCalled();
});

it('resets state and reopens when runId changes', async () => {
  const firstBody = new FakeSseBody();
  const secondBody = new FakeSseBody();
  queueFetch(streamingResponse(firstBody), streamingResponse(secondBody));
  const {result, rerender} = renderHook(
    ({id}: {id: string | null}) => useRunStream(id),
    {initialProps: {id: 'run-1' as string | null}},
  );
  await settle();
  firstBody.push({seq: 1, type: 'a', payload: {}});
  await settle();
  expect(result.current.events).toHaveLength(1);

  rerender({id: 'run-2'});
  expect(result.current.events).toEqual([]);
  expect(result.current.connection).toBe('connecting');

  await settle();
  expect(fetchMock().mock.calls[1][0]).toContain('/api/runs/run-2/events');
});

describe('connection state', () => {
  it('reports connecting then open as the stream connects', async () => {
    const body = new FakeSseBody();
    queueFetch(streamingResponse(body));
    const {result} = renderHook(() => useRunStream('run-1'));
    expect(result.current.connection).toBe('connecting');

    await settle();
    expect(result.current.connection).toBe('open');
  });

  it('reports disconnected on a permanent rejection, with no retry', async () => {
    queueFetch(errorResponse(404));
    const {result} = renderHook(() => useRunStream('run-1'));
    await settle();

    expect(result.current.connection).toBe('disconnected');
    await settle(RECONNECT_DELAY_MS);
    expect(fetchMock().mock.calls).toHaveLength(1);
  });

  it('reports reconnecting after an open stream drops, then reopens', async () => {
    const firstBody = new FakeSseBody();
    const secondBody = new FakeSseBody();
    queueFetch(streamingResponse(firstBody), streamingResponse(secondBody));
    const {result} = renderHook(() => useRunStream('run-1'));
    await settle();
    expect(result.current.connection).toBe('open');

    firstBody.end();
    await settle();
    expect(result.current.connection).toBe('reconnecting');

    await settle(RECONNECT_DELAY_MS);
    expect(result.current.connection).toBe('open');
  });
});
