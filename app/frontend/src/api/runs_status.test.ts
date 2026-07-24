import {describe, it, expect} from 'vitest';
import {isActiveStatus, isTerminalStatus, type RunStatus} from './runs';

describe('status predicates', () => {
  it('treats queued, running, and synthesizing as active', () => {
    // 'synthesizing' matters: the workflow is still cancellable and still
    // emits messages during synthesis, so the UI must treat it as active.
    const active: RunStatus[] = ['queued', 'running', 'synthesizing'];
    for (const status of active) {
      expect(isActiveStatus(status)).toBe(true);
    }
  });

  it('treats finished and draft runs as not active', () => {
    const terminal: RunStatus[] = [
      'completed',
      'failed',
      'blocked',
      'cancelled',
    ];
    for (const status of terminal) {
      expect(isActiveStatus(status)).toBe(false);
    }
    expect(isActiveStatus('draft')).toBe(false);
    expect(isActiveStatus(undefined)).toBe(false);
  });

  it('treats finished runs as terminal', () => {
    const terminal: RunStatus[] = [
      'completed',
      'failed',
      'blocked',
      'cancelled',
    ];
    for (const status of terminal) {
      expect(isTerminalStatus(status)).toBe(true);
    }
  });

  it('treats draft and in-progress runs as not terminal', () => {
    // A draft has not started, so a document it is given is still indexed
    // once it runs; queued/running/synthesizing are plainly still going.
    const nonTerminal: RunStatus[] = [
      'draft',
      'queued',
      'running',
      'synthesizing',
    ];
    for (const status of nonTerminal) {
      expect(isTerminalStatus(status)).toBe(false);
    }
    expect(isTerminalStatus(undefined)).toBe(false);
  });
});
