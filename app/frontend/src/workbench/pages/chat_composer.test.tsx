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
  // requestSubmit() ignores the submit button's disabled state, so Enter has
  // to be gated on the same condition or it bypasses the greyed-out button.
  const {onSubmit} = renderComposer({input: '   '});
  fireEvent.keyDown(screen.getByRole('textbox'), {key: 'Enter'});
  expect(onSubmit).not.toHaveBeenCalled();
});

test('blocks only submitting while the session is busy', () => {
  renderComposer({input: 'a goal', busy: true});
  // Busy means "there is nothing to send this to yet", not "go away": the
  // textarea must stay usable so the next message can be written meanwhile.
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
  // Disabling a focused element blurs it, which is what used to eject the
  // caret mid-response and force a click to get back in.
  expect(textarea).toHaveFocus();
  expect(setInput).toHaveBeenCalledWith('a goal, refined');
});

test('takes focus on mount when asked, even while busy', () => {
  // The in-conversation composer mounts busy, replacing the home one mid
  // send; without this the caret lands on the body and typing needs a click.
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
