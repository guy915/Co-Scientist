import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {NotFoundPage} from './not_found_page';

describe('NotFoundPage', () => {
  it('renders the 404 heading and message', () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole('heading', {name: 'Page not found'}),
    ).toBeInTheDocument();
    expect(screen.getByText('404')).toBeInTheDocument();
    expect(
      screen.getByText('The page you requested does not exist.'),
    ).toBeInTheDocument();
  });

  it('renders the home and workbench call-to-action links', () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', {name: 'Return home'})).toHaveAttribute(
      'href',
      '/',
    );
    expect(
      screen.getByRole('link', {name: 'Open the workbench'}),
    ).toHaveAttribute('href', '/runs');
  });
});
