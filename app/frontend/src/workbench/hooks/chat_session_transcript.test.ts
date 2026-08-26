import {expect, test} from 'vitest';
import {type InterviewTurn} from '@/api/runs';
import {turnToEntry} from './chat_session_transcript';

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
