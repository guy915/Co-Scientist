import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {ResearcherAccessPage} from './researcher_access';

vi.mock('@/api/runs', async importActual => ({
  ...(await importActual<typeof import('@/api/runs')>()),
  exchangeAccessCode: vi.fn(),
}));

describe('ResearcherAccessPage', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  it('exchanges an invite and stores only the signed session', async () => {
    vi.mocked(runsApi.exchangeAccessCode).mockResolvedValue({
      access_token: 'signed-session',
      researcher_id: 'researcher-a',
      expires_in: 3600,
    });
    render(
      <MemoryRouter>
        <ResearcherAccessPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText('Access code'), {
      target: {value: 'invite-value'},
    });
    fireEvent.click(screen.getByRole('button', {name: 'Continue'}));

    await waitFor(() =>
      expect(runsApi.exchangeAccessCode).toHaveBeenCalledWith('invite-value'),
    );
    expect(sessionStorage.getItem('co_scientist_access_token')).toBe(
      'signed-session',
    );
    expect(sessionStorage.getItem('invite-value')).toBeNull();
  });
});
