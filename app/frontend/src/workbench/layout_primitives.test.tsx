import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {ShellPopover} from './layout_primitives';

// O4: the shell's shared popover shell backs every interactive header/rail
// panel (Settings menu, Logs) -- none of them are status output, so the
// container must never carry an implicit `role="status"` live region.

it('never renders as a status live region', () => {
  render(<ShellPopover className="test-popover">content</ShellPopover>);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('renders a plain, unlabelled container when the caller names no role', () => {
  render(<ShellPopover className="test-popover">content</ShellPopover>);
  const popover = screen.getByText('content').parentElement;
  expect(popover).not.toHaveAttribute('role');
  expect(popover).not.toHaveAttribute('aria-label');
});

it('carries a labelled group role when the caller names one', () => {
  render(
    <ShellPopover className="test-popover" role="group" ariaLabel="Logs">
      content
    </ShellPopover>,
  );
  expect(screen.getByRole('group', {name: 'Logs'})).toBeInTheDocument();
});
