/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {NotFoundPage} from './NotFoundPage';

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
