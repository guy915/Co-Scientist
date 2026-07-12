import {render, screen} from '@testing-library/react';
import {MemoryRouter, Route, Routes} from 'react-router-dom';
import {describe, expect, it, vi} from 'vitest';
import {getSharedGoalReport} from '@/api/runs';
import {SharedGoalReportPage} from './shared_goal_report';

vi.mock('@/api/runs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/runs')>()),
  getSharedGoalReport: vi.fn(),
}));

describe('SharedGoalReportPage', () => {
  it('renders the four read-only report sections from a capability', async () => {
    vi.mocked(getSharedGoalReport).mockResolvedValue({
      share_id: 'share-1',
      run: {
        id: 'run-1',
        title: 'Shared pathway study',
        research_goal: 'Study pathway control',
        run_mode: 'standard',
      },
      report: {
        payload: {
          leaderboard: [],
          provider: 'engine',
          research_goal: 'Study pathway control',
          knowledge_base: [
            {
              id: 'topic-1',
              title: 'Feedback control',
              summary: 'A verified feedback mechanism.',
              detail: 'Perturbation details.',
              reference_ids: ['e1'],
            },
          ],
          agent_insights: {
            key_findings: ['Feedback is causal.'],
            uncertainties: [],
            contradictions: [],
            recommended_directions: [],
            next_experiments: [],
          },
        },
      },
      hypotheses: [],
      evidence: [],
    } as never);

    render(
      <MemoryRouter initialEntries={['/shared/token-1']}>
        <Routes>
          <Route path="/shared/:token" element={<SharedGoalReportPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole('heading', {name: 'Shared pathway study'}),
    ).toBeInTheDocument();
    for (const name of [
      'Ideas',
      'Knowledge Base',
      'Summary',
      'Run Specifications',
    ]) {
      expect(screen.getByRole('heading', {name})).toBeInTheDocument();
    }
    expect(screen.getByText('Feedback is causal.')).toBeInTheDocument();
  });
});
