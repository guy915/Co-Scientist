import {render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import * as systemStatus from '../hooks/system_status_context';
import {DiscoveryEntry, activeSuggestions} from './chat_home_stage';

describe('activeSuggestions', () => {
  it('returns SBI suggestions for sbi_ucd', () => {
    expect(activeSuggestions('sbi_ucd')[0].preview).toMatch(/MAPK/i);
  });

  it('returns default suggestions otherwise', () => {
    expect(activeSuggestions('general')[0].preview).toMatch(/glioblastoma/i);
    expect(activeSuggestions(null)[0].preview).toMatch(/glioblastoma/i);
  });
});

describe('DiscoveryEntry', () => {
  function withStatus(code_execution_available?: boolean) {
    vi.spyOn(systemStatus, 'useSystemStatus').mockReturnValue({
      status:
        code_execution_available === undefined
          ? null
          : ({code_execution_available} as never),
      unreachable: false,
    });
    render(<DiscoveryEntry />);
  }

  const entry = () => screen.queryByText(/evolve a program/i);

  it('is hidden where the deployment cannot confine code', () => {
    // Every variant of such a run is unrunnable and creation answers
    // 503, so offering the way in is offering a dead end.
    withStatus(false);
    expect(entry()).toBeNull();
  });

  it('is offered where it can', () => {
    withStatus(true);
    expect(entry()).not.toBeNull();
  });

  it('is offered while the answer is still unknown', () => {
    // The half a later refactor gets wrong: before the first poll there
    // is no answer, and hiding the product's second capability on a
    // pending fetch is worse than a refusal that says why.
    withStatus(undefined);
    expect(entry()).not.toBeNull();
  });
});
