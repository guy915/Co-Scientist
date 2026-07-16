import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {Composer} from './chat_composer';

function renderComposer(
  overrides: Partial<Parameters<typeof Composer>[0]> = {},
) {
  const props = {
    input: '',
    setInput: vi.fn(),
    disabled: false,
    onSubmit: vi.fn(e => e.preventDefault()),
    ...overrides,
  };
  render(<Composer {...props} />);
  return props;
}

describe('Composer', () => {
  it('forwards typed text to setInput', () => {
    const {setInput} = renderComposer();
    fireEvent.change(screen.getByRole('textbox'), {
      target: {value: 'ferroptosis regulators'},
    });
    expect(setInput).toHaveBeenCalledWith('ferroptosis regulators');
  });

  it('disables submit when the input is empty or whitespace', () => {
    renderComposer({input: '   '});
    const submit = screen.getByRole('button', {name: /send|start|research/i});
    expect(submit).toBeDisabled();
  });

  it('enables submit once there is real input', () => {
    renderComposer({input: 'a goal'});
    const submit = screen.getByRole('button', {name: /send|start|research/i});
    expect(submit).toBeEnabled();
  });

  it('submits on Enter without shift', () => {
    const {onSubmit} = renderComposer({input: 'a goal'});
    fireEvent.keyDown(screen.getByRole('textbox'), {key: 'Enter'});
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it('inserts a newline on Shift+Enter instead of submitting', () => {
    const {onSubmit} = renderComposer({input: 'a goal'});
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      shiftKey: true,
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('disables the textarea and submit when disabled', () => {
    renderComposer({input: 'a goal', disabled: true});
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(
      screen.getByRole('button', {name: /send|start|research/i}),
    ).toBeDisabled();
  });

  it('refocuses the textarea when it re-enables after a submit', () => {
    const props = {
      input: 'a goal',
      setInput: vi.fn(),
      disabled: true,
      onSubmit: vi.fn((e: {preventDefault: () => void}) => e.preventDefault()),
    };
    const {rerender} = render(<Composer {...props} />);
    const textarea = screen.getByRole('textbox');
    expect(textarea).not.toHaveFocus();
    // The in-flight submit ends: the textarea re-enables and focus returns.
    rerender(<Composer {...props} disabled={false} />);
    expect(textarea).toHaveFocus();
  });
});
