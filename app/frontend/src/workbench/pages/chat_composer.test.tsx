import {fireEvent, render, screen} from '@testing-library/react';
import {expect, test, vi} from 'vitest';
import {Composer} from './chat_composer';

function renderComposer(
  overrides: Partial<Parameters<typeof Composer>[0]> = {},
) {
  const props = {
    input: '',
    setInput: vi.fn(),
    busy: false,
    onSubmit: vi.fn(e => e.preventDefault()),
    ...overrides,
  };
  render(<Composer {...props} />);
  return props;
}

test('forwards typed text to setInput', () => {
  const {setInput} = renderComposer();
  fireEvent.change(screen.getByRole('textbox'), {
    target: {value: 'ferroptosis regulators'},
  });
  expect(setInput).toHaveBeenCalledWith('ferroptosis regulators');
});

test('disables submit when the input is empty or whitespace', () => {
  renderComposer({input: '   '});
  const submit = screen.getByRole('button', {name: /send|start|research/i});
  expect(submit).toBeDisabled();
});

test('enables submit once there is real input', () => {
  renderComposer({input: 'a goal'});
  const submit = screen.getByRole('button', {name: /send|start|research/i});
  expect(submit).toBeEnabled();
});

test('submits on Enter without shift', () => {
  const {onSubmit} = renderComposer({input: 'a goal'});
  fireEvent.keyDown(screen.getByRole('textbox'), {key: 'Enter'});
  expect(onSubmit).toHaveBeenCalledOnce();
});

test('inserts a newline on Shift+Enter instead of submitting', () => {
  const {onSubmit} = renderComposer({input: 'a goal'});
  fireEvent.keyDown(screen.getByRole('textbox'), {
    key: 'Enter',
    shiftKey: true,
  });
  expect(onSubmit).not.toHaveBeenCalled();
});

test('does not submit on Enter while the submit button is disabled', () => {
  // requestSubmit ignores disabled buttons; Enter must enforce the same guard.
  const {onSubmit} = renderComposer({input: '   '});
  fireEvent.keyDown(screen.getByRole('textbox'), {key: 'Enter'});
  expect(onSubmit).not.toHaveBeenCalled();
});

test('blocks only submitting while the session is busy', () => {
  renderComposer({input: 'a goal', busy: true});
  expect(screen.getByRole('textbox')).toBeEnabled();
  expect(
    screen.getByRole('button', {name: /send|start|research/i}),
  ).toBeDisabled();
});

test('keeps focus and accepts typing while the session is busy', () => {
  const {setInput} = renderComposer({input: 'a goal', busy: true});
  const textarea = screen.getByRole('textbox');
  textarea.focus();
  fireEvent.change(textarea, {target: {value: 'a goal, refined'}});
  // Disabling a focused textarea blurs it and ejects the caret mid-response.
  expect(textarea).toHaveFocus();
  expect(setInput).toHaveBeenCalledWith('a goal, refined');
});

test('takes focus on mount when asked, even while busy', () => {
  // Replacing the home composer mid-send must preserve focus.
  renderComposer({input: 'a goal', busy: true, autoFocus: true});
  expect(screen.getByRole('textbox')).toHaveFocus();
});

test('does not take focus on mount by default', () => {
  renderComposer();
  expect(screen.getByRole('textbox')).not.toHaveFocus();
});

test('does not submit on Enter while the session is busy', () => {
  const {onSubmit} = renderComposer({input: 'a goal', busy: true});
  fireEvent.keyDown(screen.getByRole('textbox'), {key: 'Enter'});
  expect(onSubmit).not.toHaveBeenCalled();
});

test('submits again on Enter once the session is no longer busy', () => {
  const props = {
    input: 'a goal',
    setInput: vi.fn(),
    busy: true,
    onSubmit: vi.fn((e: {preventDefault: () => void}) => e.preventDefault()),
  };
  const {rerender} = render(<Composer {...props} />);
  rerender(<Composer {...props} busy={false} />);
  fireEvent.keyDown(screen.getByRole('textbox'), {key: 'Enter'});
  expect(props.onSubmit).toHaveBeenCalledOnce();
});

test('shows a Stop control instead of Send while awaiting the agent', () => {
  const onStop = vi.fn();
  renderComposer({input: 'a goal', busy: true, stoppable: true, onStop});
  expect(
    screen.queryByRole('button', {name: /send|start|research/i}),
  ).not.toBeInTheDocument();
  const stop = screen.getByRole('button', {name: 'Stop'});
  expect(stop).toBeEnabled();
});

test('Stop calls onStop and does not submit the form', () => {
  const onStop = vi.fn();
  const {onSubmit} = renderComposer({
    input: 'a goal',
    busy: true,
    stoppable: true,
    onStop,
  });
  fireEvent.click(screen.getByRole('button', {name: 'Stop'}));
  expect(onStop).toHaveBeenCalledOnce();
  expect(onSubmit).not.toHaveBeenCalled();
});

test('Stop is a real button, not a submit control', () => {
  renderComposer({
    input: 'a goal',
    busy: true,
    stoppable: true,
    onStop: vi.fn(),
  });
  expect(screen.getByRole('button', {name: 'Stop'})).toHaveAttribute(
    'type',
    'button',
  );
});

test('shows Send, not Stop, once the turn resolves', () => {
  const props = {
    input: 'a goal',
    setInput: vi.fn(),
    busy: true,
    stoppable: true,
    onStop: vi.fn(),
    onSubmit: vi.fn((e: {preventDefault: () => void}) => e.preventDefault()),
  };
  const {rerender} = render(<Composer {...props} />);
  rerender(<Composer {...props} busy={false} stoppable={false} />);
  expect(screen.queryByRole('button', {name: 'Stop'})).not.toBeInTheDocument();
  expect(
    screen.getByRole('button', {name: /send|start|research/i}),
  ).toBeInTheDocument();
});
