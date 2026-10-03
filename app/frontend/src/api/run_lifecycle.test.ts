import {describe, expect, it} from 'vitest';
import {
  isActiveStatus,
  isCancelledStatus,
  isCompletedStatus,
  isDraftStatus,
  isFailureStatus,
  isStartedStatus,
  isStoppableStatus,
  isTerminalNonCompletedStatus,
  isTerminalStatus,
  retiresStartIntent,
  runActivity,
  type RunStatus,
  type TerminalNonCompletedStatus,
} from './runs';

const ALL_STATUSES: RunStatus[] = [
  'draft',
  'queued',
  'running',
  'synthesizing',
  'paused',
  'completed',
  'failed',
  'blocked',
  'cancelled',
];

type Question = (status: string | null | undefined) => boolean;

// Each question with the statuses that answer yes; every other status
// answers no. The asymmetries are the point: paused is started and stoppable
// but not active, failed/blocked are terminal but never "started", and
// cancelled retires a start intent while failed/blocked keep it.
const QUESTIONS: Record<string, {ask: Question; yes: RunStatus[]}> = {
  isActiveStatus: {
    ask: isActiveStatus,
    yes: ['queued', 'running', 'synthesizing'],
  },
  isTerminalStatus: {
    ask: isTerminalStatus,
    yes: ['completed', 'failed', 'blocked', 'cancelled'],
  },
  isStartedStatus: {
    ask: isStartedStatus,
    yes: ['queued', 'running', 'synthesizing', 'completed', 'paused'],
  },
  isStoppableStatus: {
    ask: isStoppableStatus,
    yes: ['queued', 'running', 'synthesizing', 'paused'],
  },
  isTerminalNonCompletedStatus: {
    ask: isTerminalNonCompletedStatus,
    yes: ['failed', 'cancelled', 'blocked'],
  },
  retiresStartIntent: {
    ask: retiresStartIntent,
    yes: [
      'queued',
      'running',
      'synthesizing',
      'completed',
      'paused',
      'cancelled',
    ],
  },
  isFailureStatus: {ask: isFailureStatus, yes: ['failed', 'blocked']},
  isDraftStatus: {ask: isDraftStatus, yes: ['draft']},
  isCompletedStatus: {ask: isCompletedStatus, yes: ['completed']},
  isCancelledStatus: {ask: isCancelledStatus, yes: ['cancelled']},
};

// Values a status can hold before the run loads or from a newer backend.
const UNRECOGNIZED = [undefined, null, '', 'garbage', 'toString'] as const;

describe('lifecycle questions', () => {
  it.each(Object.keys(QUESTIONS))('%s answers per status', name => {
    const {ask, yes} = QUESTIONS[name];
    for (const status of ALL_STATUSES) {
      expect(ask(status), `${name}(${status})`).toBe(yes.includes(status));
    }
  });

  it.each(Object.keys(QUESTIONS))('%s says no to unrecognized', name => {
    for (const status of UNRECOGNIZED) {
      expect(QUESTIONS[name].ask(status), `${name}(${status})`).toBe(false);
    }
  });
});

describe('status asymmetries consumers rely on', () => {
  it('counts paused as started and stoppable but not active', () => {
    expect(isStartedStatus('paused')).toBe(true);
    expect(isStoppableStatus('paused')).toBe(true);
    expect(isActiveStatus('paused')).toBe(false);
    expect(isTerminalStatus('paused')).toBe(false);
  });

  it('leaves draft neither active nor terminal, and unstoppable', () => {
    expect(isActiveStatus('draft')).toBe(false);
    expect(isTerminalStatus('draft')).toBe(false);
    expect(isStoppableStatus('draft')).toBe(false);
  });

  it('never calls failed or blocked started, and keeps their intent', () => {
    for (const status of ['failed', 'blocked']) {
      expect(isStartedStatus(status)).toBe(false);
      expect(retiresStartIntent(status)).toBe(false);
      expect(isFailureStatus(status)).toBe(true);
    }
  });

  it('retires the intent of a cancelled run that never started', () => {
    expect(isStartedStatus('cancelled')).toBe(false);
    expect(retiresStartIntent('cancelled')).toBe(true);
    expect(isFailureStatus('cancelled')).toBe(false);
  });

  it('narrows a terminal non-completed status for the end-state copy', () => {
    const status: RunStatus | undefined = 'failed' as RunStatus | undefined;
    if (isTerminalNonCompletedStatus(status)) {
      const narrowed: TerminalNonCompletedStatus = status;
      expect(narrowed).toBe('failed');
    }
  });
});

describe('runActivity', () => {
  it('is unknown until a status exists', () => {
    expect(runActivity(undefined)).toBe('unknown');
    expect(runActivity(null)).toBe('unknown');
  });

  it.each(ALL_STATUSES)('reads %s as active only while in progress', status => {
    const active = QUESTIONS.isActiveStatus.yes.includes(status);
    expect(runActivity(status)).toBe(active ? 'active' : 'inactive');
  });
});
