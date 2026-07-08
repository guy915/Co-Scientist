import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {PublicLinkButton} from './public_link_button';

describe('PublicLinkButton', () => {
  it('renders a link to the destination with its children', () => {
    render(
      <MemoryRouter>
        <PublicLinkButton to="/">Open workbench</PublicLinkButton>
      </MemoryRouter>,
    );
    const link = screen.getByRole('link', {name: 'Open workbench'});
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/');
  });

  it('applies the button styling classes', () => {
    render(
      <MemoryRouter>
        <PublicLinkButton to="/">Home</PublicLinkButton>
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', {name: 'Home'})).toHaveClass(
      'bg-[var(--md-sys-color-primary)]',
      'text-[var(--md-sys-color-on-primary)]',
    );
  });
});
