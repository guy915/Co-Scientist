import {act, renderHook} from '@testing-library/react';
import type {ReactNode} from 'react';
import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import {AudienceProvider, useAudience} from './audience_context';

const STORAGE_KEY = 'cosci-audience';

function wrapper({children}: {children: ReactNode}) {
  return <AudienceProvider>{children}</AudienceProvider>;
}

describe('audience_context', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it('starts null when nothing is stored', () => {
    const {result} = renderHook(() => useAudience(), {wrapper});
    expect(result.current.audience).toBeNull();
  });

  it('persists a chosen audience to localStorage', () => {
    const {result} = renderHook(() => useAudience(), {wrapper});
    act(() => result.current.setAudience('sbi_ucd'));
    expect(result.current.audience).toBe('sbi_ucd');
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('sbi_ucd');
  });

  it('reads a stored audience on mount', () => {
    window.localStorage.setItem(STORAGE_KEY, 'google');
    const {result} = renderHook(() => useAudience(), {wrapper});
    expect(result.current.audience).toBe('google');
  });

  it('treats an unknown stored value as null', () => {
    window.localStorage.setItem(STORAGE_KEY, 'bogus');
    const {result} = renderHook(() => useAudience(), {wrapper});
    expect(result.current.audience).toBeNull();
  });
});
