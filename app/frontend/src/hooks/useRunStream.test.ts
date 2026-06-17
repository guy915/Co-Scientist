import {describe, it, expect, vi, beforeEach} from 'vitest';
import {renderHook, act} from '@testing-library/react';
import {useRunStream, type StreamEvent} from './useRunStream';

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

/** Fires an onmessage with a JSON-encoded StreamEvent, wrapped in act(). */
function emit(es: FakeEventSource, ev: Partial<StreamEvent>): void {
  act(() => es.onmessage?.({data: JSON.stringify(ev)}));
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
});

describe('useRunStream', () => {
  it('stays idle and opens no stream when runId is null', () => {
    const {result} = renderHook(() => useRunStream(null));
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current.events).toEqual([]);
    expect(result.current.isOpen).toBe(false);
    expect(result.current.terminal).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('opens a stream against the run events URL and flips isOpen on open', () => {
    const {result} = renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();
    expect(es.url).toContain('/api/runs/run-1/events');
    expect(es.url).toContain('after=0');

    expect(result.current.isOpen).toBe(false);
    act(() => es.onopen?.());
    expect(result.current.isOpen).toBe(true);
  });

  it('accumulates streamed events and tracks the highest seq', () => {
    const {result} = renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();

    emit(es, {seq: 1, type: 'node_start', payload: {node: 'generate'}});
    emit(es, {seq: 2, type: 'node_end', payload: {node: 'generate'}});

    expect(result.current.events).toHaveLength(2);
    expect(result.current.events.map(e => e.type)).toEqual([
      'node_start',
      'node_end',
    ]);
    expect(result.current.lastSeq).toBe(2);
  });

  it('keeps the max seq even when events arrive out of order', () => {
    const {result} = renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();

    emit(es, {seq: 5, type: 'a', payload: {}});
    emit(es, {seq: 3, type: 'b', payload: {}});

    expect(result.current.events).toHaveLength(2);
    expect(result.current.lastSeq).toBe(5);
  });

  it('marks terminal and closes the stream on a _terminal event', () => {
    const {result} = renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();

    emit(es, {seq: 1, type: 'node_start', payload: {}});
    emit(es, {type: '_terminal', payload: {}});

    expect(result.current.terminal).toBe(true);
    expect(result.current.isOpen).toBe(false);
    expect(result.current.error).toBeNull();
    expect(es.close).toHaveBeenCalledOnce();
    // The terminal sentinel itself is not appended to the timeline.
    expect(result.current.events).toHaveLength(1);
  });

  it('surfaces a connection error and clears isOpen on error', () => {
    const {result} = renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();

    act(() => es.onopen?.());
    expect(result.current.isOpen).toBe(true);

    act(() => es.onerror?.());
    expect(result.current.error).toBe(
      'Connection lost; events may be incomplete.',
    );
    expect(result.current.isOpen).toBe(false);
  });

  it('ignores malformed event payloads without crashing', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const {result} = renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();

    act(() => es.onmessage?.({data: 'not json{'}));

    expect(result.current.events).toEqual([]);
    expect(result.current.error).toBeNull();
    consoleSpy.mockRestore();
  });

  it('closes the stream on unmount', () => {
    const {unmount} = renderHook(() => useRunStream('run-1'));
    const es = FakeEventSource.last();
    expect(es.close).not.toHaveBeenCalled();
    unmount();
    expect(es.close).toHaveBeenCalledOnce();
  });

  it('resets state and reopens when runId changes', () => {
    const {result, rerender} = renderHook(
      ({id}: {id: string | null}) => useRunStream(id),
      {initialProps: {id: 'run-1' as string | null}},
    );
    const first = FakeEventSource.last();
    emit(first, {seq: 1, type: 'a', payload: {}});
    expect(result.current.events).toHaveLength(1);

    rerender({id: 'run-2'});
    expect(first.close).toHaveBeenCalledOnce();
    expect(result.current.events).toEqual([]);
    expect(result.current.lastSeq).toBe(0);

    const second = FakeEventSource.last();
    expect(second).not.toBe(first);
    expect(second.url).toContain('/api/runs/run-2/events');
  });
});
