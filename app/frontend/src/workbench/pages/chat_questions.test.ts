import {expect, test} from 'vitest';
import {type InterviewQuestion, type InterviewTurn} from '@/api/runs';
import {
  answerText,
  emptySelections,
  hasOtherAnswer,
  pendingQuestions,
  setOther,
  toggleOption,
} from './chat_questions';

const MODEL_SYSTEM: InterviewQuestion = {
  header: 'Model system',
  question: 'Which model system should the ideas be built around?',
  multi_select: false,
  options: [
    {label: 'Primary human cells', description: 'Closest to patient biology'},
    {label: 'iPSC-derived line', description: 'Renewable and editable'},
  ],
};

const EXCLUSIONS: InterviewQuestion = {
  header: '',
  question: 'Which directions should be excluded?',
  multi_select: true,
  options: [
    {label: 'Gene therapy', description: ''},
    {label: 'Small molecules', description: ''},
    {label: 'Devices', description: ''},
  ],
};

function turn(questions: InterviewQuestion[], overrides = {}) {
  return {
    id: 1,
    role: 'agent' as const,
    content: 'Which model system?',
    reasoning: null,
    fallback: false,
    questions,
    created_at: 1,
    ...overrides,
  };
}

test('a chosen answer is sent under the header naming what it answers', () => {
  const selections = toggleOption(
    emptySelections(),
    0,
    'Primary human cells',
    false,
  );
  expect(answerText([MODEL_SYSTEM], selections)).toBe(
    'Model system: Primary human cells',
  );
});

test('a headerless question sends the bare answer', () => {
  const selections = toggleOption(emptySelections(), 0, 'Gene therapy', true);
  expect(answerText([EXCLUSIONS], selections)).toBe('Gene therapy');
});

test('a single-select question keeps only the last answer clicked', () => {
  let selections = toggleOption(
    emptySelections(),
    0,
    'Primary human cells',
    false,
  );
  selections = toggleOption(selections, 0, 'iPSC-derived line', false);
  expect(answerText([MODEL_SYSTEM], selections)).toBe(
    'Model system: iPSC-derived line',
  );
});

test('a multi-select question accumulates answers and clicking again removes one', () => {
  let selections = toggleOption(emptySelections(), 0, 'Gene therapy', true);
  selections = toggleOption(selections, 0, 'Devices', true);
  selections = toggleOption(selections, 0, 'Gene therapy', true);
  expect(answerText([EXCLUSIONS], selections)).toBe('Devices');
});

test('several answered questions are sent one per line', () => {
  let selections = toggleOption(
    emptySelections(),
    0,
    'iPSC-derived line',
    false,
  );
  selections = toggleOption(selections, 1, 'Devices', true);
  expect(answerText([MODEL_SYSTEM, EXCLUSIONS], selections)).toBe(
    'Model system: iPSC-derived line\nDevices',
  );
});

test('an unanswered question contributes nothing', () => {
  const selections = toggleOption(emptySelections(), 1, 'Devices', true);
  expect(answerText([MODEL_SYSTEM, EXCLUSIONS], selections)).toBe('Devices');
});

test('nothing chosen is nothing to send', () => {
  expect(answerText([MODEL_SYSTEM], emptySelections())).toBe('');
});

test("the scientist's own wording is sent alongside what they clicked", () => {
  const selections = {
    ...toggleOption(emptySelections(), 0, 'Gene therapy', true),
    other: {0: '  anything needing a BSL-3 suite  '},
  };
  expect(answerText([EXCLUSIONS], selections)).toBe(
    'Gene therapy, anything needing a BSL-3 suite',
  );
});

test('only the last Agent turn of an active interview still awaits an answer', () => {
  expect(
    pendingQuestions({
      turns: [turn([MODEL_SYSTEM], {id: 1}), turn([EXCLUSIONS], {id: 2})],
      status: 'active',
    }),
  ).toEqual({turnId: 2, questions: [EXCLUSIONS]});
});

test('a question the scientist has already answered is not re-offered', () => {
  expect(
    pendingQuestions({
      turns: [
        turn([MODEL_SYSTEM], {id: 1}),
        {...turn([], {id: 2}), role: 'user' as const, content: 'iPSC'},
      ],
      status: 'active',
    }),
  ).toBeNull();
});

test('a completed interview offers nothing, however its last turn ended', () => {
  expect(
    pendingQuestions({
      turns: [turn([MODEL_SYSTEM])],
      status: 'completed',
    }),
  ).toBeNull();
});

test('no interview at all offers nothing', () => {
  expect(pendingQuestions(null)).toBeNull();
});

test('blank or whitespace-only free text is not yet an answer', () => {
  expect(hasOtherAnswer(emptySelections(), 0)).toBe(false);
  const selections = setOther(emptySelections(), 0, '   ');
  expect(hasOtherAnswer(selections, 0)).toBe(false);
  expect(answerText([MODEL_SYSTEM], selections)).toBe('');
});

test('typing non-blank free text is what answers the question', () => {
  const selections = setOther(emptySelections(), 0, 'A scaffold');
  expect(hasOtherAnswer(selections, 0)).toBe(true);
  expect(answerText([MODEL_SYSTEM], selections)).toBe(
    'Model system: A scaffold',
  );
});

test('clearing the free-text field un-answers the question', () => {
  let selections = setOther(emptySelections(), 0, 'A scaffold');
  selections = setOther(selections, 0, '');
  expect(hasOtherAnswer(selections, 0)).toBe(false);
  expect(answerText([MODEL_SYSTEM], selections)).toBe('');
});

test('a turn from before the chooser existed offers nothing, and crashes nothing', () => {
  const legacy = {
    id: 1,
    role: 'agent',
    content: 'Which one?',
    reasoning: null,
    fallback: false,
    created_at: 1,
  };
  expect(
    pendingQuestions({
      turns: [legacy as unknown as InterviewTurn],
      status: 'active',
    }),
  ).toBeNull();
});
