import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {Button, buttonClasses} from './button';
import {IconButton} from './icon_button';

it('defaults to a non-submitting filled pill with the shared focus ring', () => {
  render(<Button>Save</Button>);
  const button = screen.getByRole('button', {name: 'Save'});
  expect(button).toHaveAttribute('type', 'button');
  expect(button.className).toContain('rounded-full');
  expect(button.className).toContain('bg-button-filled-bg');
  expect(button.className).toContain('focus-visible:outline-th-ring');
});

it('gives every variant the same shape', () => {
  for (const variant of ['filled', 'outlined', 'tonal', 'text'] as const) {
    expect(buttonClasses({variant})).toContain('rounded-full');
  }
});

it('shows a tooltip only when asked', () => {
  render(
    <>
      <Button>Plain</Button>
      <Button tooltip="More detail">Tipped</Button>
    </>,
  );
  expect(screen.getByRole('button', {name: 'Plain'})).not.toHaveAttribute(
    'data-tooltip',
  );
  const tipped = screen.getByRole('button', {name: 'Tipped'});
  expect(tipped).toHaveAttribute('data-tooltip', 'More detail');
  expect(tipped.className).toContain('ucs-tooltip-top');
});

it('names an icon button from its label and tooltips it by default', () => {
  render(<IconButton icon="close" label="Close settings" />);
  const button = screen.getByRole('button', {name: 'Close settings'});
  expect(button).toHaveAttribute('data-tooltip', 'Close settings');
  expect(button.className).toContain('rounded-full');
});

it('lets an icon button drop the tooltip or change its text', () => {
  render(
    <>
      <IconButton icon="close" label="Close" tooltip={null} />
      <IconButton icon="add" label="Add" tooltip="Add a row" />
    </>,
  );
  expect(screen.getByRole('button', {name: 'Close'})).not.toHaveAttribute(
    'data-tooltip',
  );
  expect(screen.getByRole('button', {name: 'Add'})).toHaveAttribute(
    'data-tooltip',
    'Add a row',
  );
});
