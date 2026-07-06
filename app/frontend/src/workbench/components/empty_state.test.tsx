import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {EmptyState} from './empty_state';

describe('EmptyState', () => {
  it('renders its children', () => {
    render(<EmptyState>No evidence yet</EmptyState>);
    expect(screen.getByText('No evidence yet')).toBeInTheDocument();
  });

  it('applies the base classes', () => {
    render(<EmptyState>body</EmptyState>);
    const el = screen.getByText('body');
    expect(el).toHaveClass(
      'rounded',
      'border',
      'p-6',
      'text-sm',
      'text-center',
    );
  });

  it('appends an optional className without dropping the base classes', () => {
    render(<EmptyState className="mt-4">body</EmptyState>);
    const el = screen.getByText('body');
    expect(el).toHaveClass('mt-4');
    expect(el).toHaveClass('rounded', 'border');
  });
});
