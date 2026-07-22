import {render} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {ProposalsPage} from './proposals_page';

export function renderPage(path = '/proposals') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ProposalsPage />
    </MemoryRouter>,
  );
}
