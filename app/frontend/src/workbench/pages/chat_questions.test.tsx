import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, test, vi} from 'vitest';
import {type InterviewQuestion, type InterviewTurn} from '@/api/runs';
import {
  QuestionChooser,
  answerText,
  emptySelections,
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
  header: 'Exclusions',
  question: 'Which directions should be excluded?',
  multi_select: true,
  options: [
    {label: 'Gene therapy', description: ''},
    {label: 'Devices', description: ''},
  ],
};

function renderChooser(
  questions: InterviewQuestion[] = [MODEL_SYSTEM],
  overrides: Partial<Parameters<typeof QuestionChooser>[0]> = {},
) {
  const props = {questions, onAnswer: vi.fn(), ...overrides};
  render(<QuestionChooser {...props} />);
  return props;
}

test('asks the question and lays out every answer with its description', () => {
  renderChooser();
  expect(screen.getByText(MODEL_SYSTEM.question)).toBeTruthy();
  expect(screen.getByLabelText(/Primary human cells/)).toBeTruthy();
  expect(screen.getByText('Closest to patient biology')).toBeTruthy();
});

test('clicking an answer only selects it, even for one single-select question', () => {
  const {onAnswer} = renderChooser();
  fireEvent.click(screen.getByLabelText(/iPSC-derived line/));
  expect(onAnswer).not.toHaveBeenCalled();
});

test('a single-select question still has its own send control', () => {
  renderChooser();
  expect(screen.getByRole('button', {name: /send/i})).toBeTruthy();
});

test('the send control commits a single-select answer once clicked', () => {
  const {onAnswer} = renderChooser();
  fireEvent.click(screen.getByLabelText(/iPSC-derived line/));
  fireEvent.click(screen.getByRole('button', {name: /send/i}));
  expect(onAnswer).toHaveBeenCalledWith('Model system: iPSC-derived line');
});

test('a multi-select question waits for the send control', () => {
  const {onAnswer} = renderChooser([EXCLUSIONS]);
  fireEvent.click(screen.getByLabelText(/Gene therapy/));
  fireEvent.click(screen.getByLabelText(/Devices/));
  expect(onAnswer).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', {name: /send/i}));
  expect(onAnswer).toHaveBeenCalledWith('Exclusions: Gene therapy, Devices');
});

test('the send control is inert until something has been chosen', () => {
  renderChooser([EXCLUSIONS]);
  expect(screen.getByRole('button', {name: /send/i})).toBeDisabled();
});

test('a multi-select question renders checkboxes and holds several answers at once', () => {
  const {onAnswer} = renderChooser([EXCLUSIONS]);
  const geneTherapy = screen.getByLabelText(/Gene therapy/) as HTMLInputElement;
  const devices = screen.getByLabelText(/Devices/) as HTMLInputElement;
  expect(geneTherapy.type).toBe('checkbox');
  expect(devices.type).toBe('checkbox');
  fireEvent.click(geneTherapy);
  fireEvent.click(devices);
  expect(geneTherapy.checked).toBe(true);
  expect(devices.checked).toBe(true);
  fireEvent.click(screen.getByRole('button', {name: /send/i}));
  expect(onAnswer).toHaveBeenCalledWith('Exclusions: Gene therapy, Devices');
});

test('the free-text field is already there, with no click needed to reveal it', () => {
  renderChooser();
  expect(screen.getByPlaceholderText(/your own answer/i)).toBeTruthy();
});

test('typing into "Something else" is what answers it', () => {
  const {onAnswer} = renderChooser();
  fireEvent.change(screen.getByLabelText(/Something else/), {
    target: {value: 'A decellularized scaffold'},
  });
  fireEvent.click(screen.getByRole('button', {name: /send/i}));
  expect(onAnswer).toHaveBeenCalledWith(
    'Model system: A decellularized scaffold',
  );
});

test('a keystroke never sends the free-text answer, even for a single question', () => {
  const {onAnswer} = renderChooser();
  fireEvent.change(screen.getByLabelText(/Something else/), {
    target: {value: 'A'},
  });
  expect(onAnswer).not.toHaveBeenCalled();
  expect(screen.getByRole('button', {name: /send/i})).toBeTruthy();
});

test('pressing Enter in the free-text field does not submit anything', () => {
  const {onAnswer} = renderChooser();
  const field = screen.getByLabelText(/Something else/);
  fireEvent.change(field, {target: {value: 'A decellularized scaffold'}});
  // jsdom lacks implicit Enter submission; preventDefault proves the guard
  // fired.
  expect(fireEvent.keyDown(field, {key: 'Enter'})).toBe(false);
  expect(onAnswer).not.toHaveBeenCalled();
});

test('the answers render as a single column of full-width rows', () => {
  renderChooser();
  const group = screen.getByRole('group', {name: MODEL_SYSTEM.question});
  const grid = group.querySelector(':scope > div');
  expect(grid?.className).toMatch(/grid-cols-1\b/);
});

test('there is a touch more room between the question and its first option', () => {
  renderChooser();
  const group = screen.getByRole('group', {name: MODEL_SYSTEM.question});
  const grid = group.querySelector(':scope > div');
  expect(grid?.className).toMatch(/mt-\[0\.15rem\]/);
});

test('dismissing the chooser leaves nothing of it on screen', () => {
  renderChooser();
  fireEvent.click(screen.getByRole('button', {name: /dismiss/i}));
  expect(screen.queryByText(MODEL_SYSTEM.question)).toBeNull();
});

test('minimizing keeps the chooser reachable without it taking the room', () => {
  renderChooser();
  fireEvent.click(screen.getByRole('button', {name: /minimize/i}));
  expect(screen.queryByLabelText(/Primary human cells/)).toBeNull();
  fireEvent.click(screen.getByRole('button', {name: /show.*question/i}));
  expect(screen.getByLabelText(/Primary human cells/)).toBeTruthy();
});

test('several questions are stacked, and the send control answers them together', () => {
  const {onAnswer} = renderChooser([MODEL_SYSTEM, EXCLUSIONS]);
  fireEvent.click(screen.getByLabelText(/Primary human cells/));
  expect(onAnswer).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText(/Devices/));
  fireEvent.click(screen.getByRole('button', {name: /send/i}));
  expect(onAnswer).toHaveBeenCalledWith(
    'Model system: Primary human cells\nExclusions: Devices',
  );
});

describe('answer state and pending questions', () => {
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
    const selections = setOther(
      toggleOption(emptySelections(), 0, 'Gene therapy', true),
      0,
      '  anything needing a BSL-3 suite  ',
    );
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
});
