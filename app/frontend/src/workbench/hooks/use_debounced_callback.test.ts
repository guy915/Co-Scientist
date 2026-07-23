import {renderHook} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {useDebouncedCallback} from './use_debounced_callback';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

it('invokes on the trailing edge after the delay', () => {
  const fn = vi.fn();
  const {result} = renderHook(() => useDebouncedCallback(fn, 500));

  result.current();
  expect(fn).not.toHaveBeenCalled();

  vi.advanceTimersByTime(499);
  expect(fn).not.toHaveBeenCalled();

  vi.advanceTimersByTime(1);
  expect(fn).toHaveBeenCalledOnce();
});

it('collapses a burst of calls into one with the latest args', () => {
  const fn = vi.fn<(value: string) => void>();
  const {result} = renderHook(() => useDebouncedCallback(fn, 500));

  result.current('a');
  vi.advanceTimersByTime(200);
  result.current('b');
  vi.advanceTimersByTime(200);
  result.current('c');
  expect(fn).not.toHaveBeenCalled();

  vi.advanceTimersByTime(500);
  expect(fn).toHaveBeenCalledOnce();
  expect(fn).toHaveBeenCalledWith('c');
});

it('restarts the delay window on each new call', () => {
  const fn = vi.fn();
  const {result} = renderHook(() => useDebouncedCallback(fn, 500));

  result.current();
  vi.advanceTimersByTime(400);
  result.current();
  vi.advanceTimersByTime(400);
  expect(fn).not.toHaveBeenCalled();

  vi.advanceTimersByTime(100);
  expect(fn).toHaveBeenCalledOnce();
});

it('fires again for calls made after a completed invocation', () => {
  const fn = vi.fn();
  const {result} = renderHook(() => useDebouncedCallback(fn, 500));

  result.current();
  vi.advanceTimersByTime(500);
  result.current();
  vi.advanceTimersByTime(500);
  expect(fn).toHaveBeenCalledTimes(2);
});

it('cancels pending work on unmount', () => {
  const fn = vi.fn();
  const {result, unmount} = renderHook(() => useDebouncedCallback(fn, 500));

  result.current();
  unmount();
  vi.advanceTimersByTime(1000);
  expect(fn).not.toHaveBeenCalled();
});

it('flush runs a pending invocation immediately, exactly once', () => {
  const fn = vi.fn<(value: number) => void>();
  const {result} = renderHook(() => useDebouncedCallback(fn, 500));

  result.current(7);
  result.current.flush();
  expect(fn).toHaveBeenCalledOnce();
  expect(fn).toHaveBeenCalledWith(7);

  vi.advanceTimersByTime(1000);
  expect(fn).toHaveBeenCalledOnce();
});

it('flush is a no-op when nothing is pending', () => {
  const fn = vi.fn();
  const {result} = renderHook(() => useDebouncedCallback(fn, 500));

  result.current.flush();
  expect(fn).not.toHaveBeenCalled();
});

it('cancel drops pending work without running it', () => {
  const fn = vi.fn();
  const {result} = renderHook(() => useDebouncedCallback(fn, 500));

  result.current();
  result.current.cancel();
  vi.advanceTimersByTime(1000);
  expect(fn).not.toHaveBeenCalled();

  // The wrapper still works after a cancel.
  result.current();
  vi.advanceTimersByTime(500);
  expect(fn).toHaveBeenCalledOnce();
});

it('keeps a stable identity and always invokes the latest callback', () => {
  const first = vi.fn();
  const second = vi.fn();
  const {result, rerender} = renderHook(
    ({fn}: {fn: () => void}) => useDebouncedCallback(fn, 500),
    {initialProps: {fn: first}},
  );
  const initial = result.current;

  result.current();
  rerender({fn: second});
  expect(result.current).toBe(initial);

  vi.advanceTimersByTime(500);
  expect(first).not.toHaveBeenCalled();
  expect(second).toHaveBeenCalledOnce();
});
