import {fireEvent, render, screen} from '@testing-library/react';
import {expect, test, vi} from 'vitest';
import {type InterviewQuestion} from '@/api/runs';
import {QuestionChooser} from './chat_questions_panel';

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

test('one single-select question sends the moment an answer is clicked', () => {
  const {onAnswer} = renderChooser();
  fireEvent.click(screen.getByLabelText(/iPSC-derived line/));
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
  // fireEvent returns false when the handler called preventDefault, which is
  // what actually proves the guard fired -- jsdom has no implicit form
  // submission for Enter to begin with, so `onAnswer` alone can't tell.
  expect(fireEvent.keyDown(field, {key: 'Enter'})).toBe(false);
  expect(onAnswer).not.toHaveBeenCalled();
});

test('the answers render as a single column of full-width rows', () => {
  renderChooser();
  const group = screen.getByRole('group', {name: MODEL_SYSTEM.question});
  const grid = group.querySelector(':scope > div');
  expect(grid?.className).toMatch(/grid-cols-1\b/);
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
