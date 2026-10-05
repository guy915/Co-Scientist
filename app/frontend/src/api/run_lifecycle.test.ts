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
} from './runs';

describe('run lifecycle', () => {
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

  // Paused, active, terminal and start-intent predicates deliberately have
  // different boundaries.
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

  describe('runActivity', () => {
    it('is unknown until a status exists', () => {
      expect(runActivity(undefined)).toBe('unknown');
      expect(runActivity(null)).toBe('unknown');
    });

    it.each(ALL_STATUSES)(
      'reads %s as active only while in progress',
      status => {
        const active = QUESTIONS.isActiveStatus.yes.includes(status);
        expect(runActivity(status)).toBe(active ? 'active' : 'inactive');
      },
    );
  });
});
