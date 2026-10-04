import {expect, test} from 'vitest';
import {type Interview, type InterviewTurn} from '@/api/runs';
import {
  applyInterview,
  turnToEntry,
  type TranscriptSink,
} from './chat_session_transcript';

function makeTurn(overrides: Partial<InterviewTurn> = {}): InterviewTurn {
  return {
    id: 1,
    role: 'agent',
    content: 'Which focus area should this research prioritize?',
    reasoning: null,
    fallback: false,
    questions: [],
    created_at: 1,
    ...overrides,
  };
}

test('turnToEntry carries the fallback marker for scripted turns', () => {
  const entry = turnToEntry(makeTurn({fallback: true}));
  expect(entry.fallback).toBe(true);
});

test('turnToEntry leaves model-driven turns unmarked', () => {
  const entry = turnToEntry(makeTurn());
  expect(entry.fallback).toBeUndefined();
});

function completedInterview(runId: string | null): Interview {
  return {
    id: 'chat-1',
    client_id: 'client-1',
    status: 'completed',
    fields: {
      research_challenge: 'Reverse liver fibrosis.',
      focus_area: ['Stellate cells'],
      preferences: ['Preclinical only'],
      title: 'Fibrosis reversal',
    },
    current_question: null,
    turns: [
      makeTurn({id: 1, role: 'user', content: 'Reverse liver fibrosis.'}),
      makeTurn({id: 2, content: 'The scope is settled.', created_at: 7}),
    ],
    documents: [],
    created_at: 1,
    updated_at: 7,
    completed_at: 7,
    run_id: runId,
  };
}

function recordingSink() {
  const calls = {draft: [] as unknown[], confirmed: [] as unknown[]};
  const sink: TranscriptSink = {
    setMessages: () => undefined,
    setInterview: () => undefined,
    setDraft: value => calls.draft.push(value),
    setConfirmed: value => calls.confirmed.push(value),
    stageDraftSpec: (...args) => calls.draft.push(args),
  };
  return {sink, calls};
}

test('a completed interview with no run stages an editable plan', () => {
  const {sink, calls} = recordingSink();
  applyInterview(sink, completedInterview(null));
  expect(calls.draft).toHaveLength(1);
  expect(calls.confirmed).toHaveLength(0);
});

// A reopened started chat must not offer a second run from the same plan.
test('a completed interview whose run started comes back settled', () => {
  const {sink, calls} = recordingSink();
  applyInterview(sink, completedInterview('run-1'));
  expect(calls.draft).toEqual([null]);
  expect(calls.confirmed).toHaveLength(1);
  const stage = calls.confirmed[0] as {intro?: string; createdAt: number};
  expect(stage.intro).toBe('The scope is settled.');
  expect(stage.createdAt).toBe(7);
});
