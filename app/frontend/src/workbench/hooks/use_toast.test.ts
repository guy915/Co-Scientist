import {act, renderHook} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {useToast} from './use_toast';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useToast', () => {
  it('starts with no toast', () => {
    const {result} = renderHook(() => useToast());
    expect(result.current.toast).toBeNull();
  });

  it('shows a toast and auto-clears it after the duration', async () => {
    const {result} = renderHook(() => useToast(3000));

    await act(async () => result.current.setToast('Saved'));
    expect(result.current.toast).toBe('Saved');

    await act(async () => vi.advanceTimersByTime(2999));
    expect(result.current.toast).toBe('Saved');

    await act(async () => vi.advanceTimersByTime(1));
    expect(result.current.toast).toBeNull();
  });

  it('resets the timer when a new toast replaces the current one', async () => {
    const {result} = renderHook(() => useToast(3000));

    await act(async () => result.current.setToast('first'));
    await act(async () => vi.advanceTimersByTime(2000));
    await act(async () => result.current.setToast('second'));

    // The original 3s window would have elapsed here, but the timer restarted.
    await act(async () => vi.advanceTimersByTime(2000));
    expect(result.current.toast).toBe('second');

    await act(async () => vi.advanceTimersByTime(1000));
    expect(result.current.toast).toBeNull();
  });

  it('respects a custom duration', async () => {
    const {result} = renderHook(() => useToast(500));
    await act(async () => result.current.setToast('quick'));
    await act(async () => vi.advanceTimersByTime(500));
    expect(result.current.toast).toBeNull();
  });
});
