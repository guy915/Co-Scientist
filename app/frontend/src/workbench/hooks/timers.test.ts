import {act, renderHook} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {useToast} from './timers';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

it('shows a toast and auto-clears it after the duration', async () => {
  const {result} = renderHook(() => useToast(3000));

  await act(async () => result.current.setToast('Saved'));
  expect(result.current.toast).toEqual({message: 'Saved'});

  await act(async () => vi.advanceTimersByTime(2999));
  expect(result.current.toast).toEqual({message: 'Saved'});

  await act(async () => vi.advanceTimersByTime(1));
  expect(result.current.toast).toBeNull();
});

it('resets the timer when a new toast replaces the current one', async () => {
  const {result} = renderHook(() => useToast(3000));

  await act(async () => result.current.setToast('first'));
  await act(async () => vi.advanceTimersByTime(2000));
  await act(async () => result.current.setToast('second'));

  await act(async () => vi.advanceTimersByTime(2000));
  expect(result.current.toast).toEqual({message: 'second'});

  await act(async () => vi.advanceTimersByTime(1000));
  expect(result.current.toast).toBeNull();
});
