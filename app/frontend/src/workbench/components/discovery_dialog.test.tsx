import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {AudienceProvider} from '../audience_context';
import {DiscoveryDialog} from './discovery_dialog';

const createRun = vi.fn();
const startRun = vi.fn();
const navigate = vi.fn();

vi.mock('@/api/runs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/runs')>()),
  createRun: (input: unknown) => createRun(input),
  startRun: (id: string) => startRun(id),
}));

vi.mock('react-router-dom', async importOriginal => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => navigate,
}));

function open() {
  return render(
    <MemoryRouter>
      <AudienceProvider>
        <DiscoveryDialog onClose={vi.fn()} />
      </AudienceProvider>
    </MemoryRouter>,
  );
}

describe('DiscoveryDialog', () => {
  beforeEach(() => {
    createRun.mockReset().mockResolvedValue({id: 'r1'});
    startRun.mockReset().mockResolvedValue({id: 'r1', status: 'running'});
    navigate.mockReset();
  });

  it('creates and starts the run in one action', async () => {
    // A discovery run has no interview to come back to, so leaving a
    // draft behind would leave the reader with nothing to do next.
    open();
    await userEvent.type(
      screen.getByPlaceholderText('Find a faster prime sieve'),
      'Beat the baseline',
    );
    await userEvent.click(screen.getByText('Start the search'));

    await waitFor(() => expect(startRun).toHaveBeenCalledWith('r1'));
    const sent = createRun.mock.calls[0][0];
    expect(sent.research_goal).toBe('Beat the baseline');
    expect(sent.discovery.stages[0].argv).toEqual(['python3', 'main.py']);
    expect(navigate).toHaveBeenCalledWith('/runs/r1/variants');
  });

  it('says what is missing instead of sending an unstartable spec', async () => {
    open();
    await userEvent.click(screen.getByText('Start the search'));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Say what the run is for.',
    );
    expect(createRun).not.toHaveBeenCalled();
  });

  it('reports a refused spec rather than closing on a failure', async () => {
    // The backend validates the spec too and is the authority; a 422
    // here has to reach the reader, not vanish.
    createRun.mockRejectedValue(new Error('422 invalid discovery spec'));
    open();
    await userEvent.type(
      screen.getByPlaceholderText('Find a faster prime sieve'),
      'Beat the baseline',
    );
    await userEvent.click(screen.getByText('Start the search'));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'invalid discovery spec',
    );
    expect(navigate).not.toHaveBeenCalled();
  });
});
