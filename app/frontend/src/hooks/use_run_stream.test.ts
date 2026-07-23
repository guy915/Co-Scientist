import {describe, it, expect, vi, beforeEach} from 'vitest';
import {renderHook, act} from '@testing-library/react';
import {useRunStream, type StreamEvent} from './use_run_stream';

// jsdom has no EventSource, so we install a controllable fake. Each constructed
// instance is recorded in `instances` so a test can reach in and fire handlers.
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: {data: string}) => void) | null = null;
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  /** Returns the most recently constructed instance. */
  static last(): FakeEventSource {
    const es = FakeEventSource.instances.at(-1);
    if (!es) throw new Error('no EventSource was constructed');
    return es;
  }
}

/**
 * Fires an onmessage with a JSON-encoded StreamEvent and waits one macrotask
 * so the hook's batched setTimeout(0) flush lands before assertions.
 */
async function emit(
  es: FakeEventSource,
  ev: Partial<StreamEvent>,
): Promise<void> {
  await act(async () => {
    es.onmessage?.({data: JSON.stringify(ev)});
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
});

describe('stream setup', () => {
  it('stays idle and opens no stream when runId is null', () => {
    const {result} = renderHook(() => useRunStream(null));
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current.events).toEqual([]);
    expect(result.current.terminal).toBe(false);
  });

  it('opens a stream against the run events URL', () => {
    renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();
    expect(es.url).toContain('/api/runs/run-1/events');
  });
});

it('accumulates streamed events and tracks the highest seq', async () => {
  const {result} = renderHook(() => useRunStream('run-1'));
  const es = FakeEventSource.last();

  await emit(es, {seq: 1, type: 'node_start', payload: {node: 'generate'}});
  await emit(es, {seq: 2, type: 'node_end', payload: {node: 'generate'}});

  expect(result.current.events).toHaveLength(2);
  expect(result.current.events.map(e => e.type)).toEqual([
    'node_start',
    'node_end',
  ]);
});

it('appends events in arrival order', async () => {
  const {result} = renderHook(() => useRunStream('run-1'));
  const es = FakeEventSource.last();

  await emit(es, {seq: 5, type: 'a', payload: {}});
  await emit(es, {seq: 3, type: 'b', payload: {}});

  expect(result.current.events).toHaveLength(2);
  expect(result.current.events.map(e => e.seq)).toEqual([5, 3]);
});

it('buffers a replay burst and flushes it on the next tick', async () => {
  const {result} = renderHook(() => useRunStream('run-1'));
  const es = FakeEventSource.last();

  // Fire the whole burst within one task, without letting the flush timer
  // run. A per-event setEvents would surface these on act() exit; because
  // they are buffered, state is still empty here. This assertion is what
  // distinguishes the batched implementation from the naive one.
  act(() => {
    for (let seq = 1; seq <= 50; seq++) {
      es.onmessage?.({
        data: JSON.stringify({seq, type: 'node', payload: {}}),
      });
    }
  });
  expect(result.current.events).toEqual([]);

  // Let the single scheduled flush fire; the whole burst lands at once.
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });

  expect(result.current.events).toHaveLength(50);
  expect(result.current.events.map(e => e.seq)).toEqual(
    Array.from({length: 50}, (_, i) => i + 1),
  );
});

describe('terminal events', () => {
  it('marks terminal and closes the stream on a _terminal event', async () => {
    const {result} = renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();

    await emit(es, {seq: 1, type: 'node_start', payload: {}});
    await emit(es, {type: '_terminal', payload: {}});

    expect(result.current.terminal).toBe(true);
    expect(es.close).toHaveBeenCalledOnce();
    // The terminal sentinel itself is not appended to the timeline.
    expect(result.current.events).toHaveLength(1);
  });

  it('drains buffered events before marking terminal', () => {
    const {result} = renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();

    // Terminal arrives in the same task as still-buffered events, before any
    // flush timer has fired. Nothing may be lost.
    act(() => {
      es.onmessage?.({
        data: JSON.stringify({seq: 1, type: 'a', payload: {}}),
      });
      es.onmessage?.({
        data: JSON.stringify({seq: 2, type: 'b', payload: {}}),
      });
      es.onmessage?.({
        data: JSON.stringify({type: '_terminal', payload: {}}),
      });
    });

    expect(result.current.events).toHaveLength(2);
    expect(result.current.events.map(e => e.seq)).toEqual([1, 2]);
    expect(result.current.terminal).toBe(true);
    expect(es.close).toHaveBeenCalledOnce();
  });
});

describe('malformed payloads', () => {
  it('ignores malformed event payloads without crashing', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const {result} = renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();

    await act(async () => {
      es.onmessage?.({data: 'not json{'});
      await new Promise(resolve => setTimeout(resolve, 0));
    });

    expect(result.current.events).toEqual([]);
    consoleSpy.mockRestore();
  });
});

it('closes the stream on unmount', () => {
  const {unmount} = renderHook(() => useRunStream('run-1'));
  const es = FakeEventSource.last();
  expect(es.close).not.toHaveBeenCalled();
  unmount();
  expect(es.close).toHaveBeenCalledOnce();
});

it('resets state and reopens when runId changes', async () => {
  const {result, rerender} = renderHook(
    ({id}: {id: string | null}) => useRunStream(id),
    {initialProps: {id: 'run-1' as string | null}},
  );
  const first = FakeEventSource.last();
  await emit(first, {seq: 1, type: 'a', payload: {}});
  expect(result.current.events).toHaveLength(1);

  rerender({id: 'run-2'});
  expect(first.close).toHaveBeenCalledOnce();
  expect(result.current.events).toEqual([]);

  const second = FakeEventSource.last();
  expect(second).not.toBe(first);
  expect(second.url).toContain('/api/runs/run-2/events');
});

it('drops the unflushed buffer on runId change (no leak)', async () => {
  const {result, rerender} = renderHook(
    ({id}: {id: string | null}) => useRunStream(id),
    {initialProps: {id: 'run-1' as string | null}},
  );
  const first = FakeEventSource.last();

  // Buffer a run-1 event WITHOUT letting its flush timer fire, then switch
  // runs. Cleanup must clear the pending timer; otherwise the stale flush
  // appends run-1's event to run-2's freshly-reset state.
  act(() => {
    first.onmessage?.({
      data: JSON.stringify({seq: 1, type: 'a', payload: {}}),
    });
  });
  rerender({id: 'run-2'});

  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });

  expect(result.current.events).toEqual([]);
});
