import type {ReactElement} from 'react';
import {it, expect} from 'vitest';
import {render, screen, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {IdeasTab} from './ideas_tab';
import type {Hypothesis, Review} from '@/api/runs';
import {makeHypothesis} from '@/test_fixtures';

// The rows are links carrying the selection in ?idea=, so the tab needs a
// router around it.
function renderIdeas(ui: ReactElement, path = '/runs/run-1/ideas') {
  return render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);
}

it('shows the empty state when there are no hypotheses', () => {
  renderIdeas(<IdeasTab hypotheses={[]} reviews={[]} />);
  expect(
    screen.getByText('Hypotheses appear here once the generation node runs.'),
  ).toBeInTheDocument();
});

it('renders idea rows sorted by Elo with their scores', () => {
  const hypotheses: Hypothesis[] = [
    makeHypothesis({
      id: 'low',
      title: 'Low-ranked idea',
      statement: 'A weaker statement.',
      elo_rating: 1150,
    }),
    makeHypothesis({
      id: 'high',
      title: 'High-ranked idea',
      statement: 'A stronger statement.',
      elo_rating: 1300,
      win_count: 4,
      loss_count: 1,
    }),
  ];
  renderIdeas(<IdeasTab hypotheses={hypotheses} reviews={[]} />);
  expect(screen.getAllByText('High-ranked idea')[0]).toBeInTheDocument();
  expect(screen.getByText('Low-ranked idea')).toBeInTheDocument();
  // Default sort is by Elo descending; the higher Elo badge is rendered.
  expect(screen.getByText('Elo rating: 1300')).toBeInTheDocument();
  expect(screen.queryByText('80% wins')).not.toBeInTheDocument();

  const rows = screen.getAllByRole('listitem');
  expect(rows[0]).toHaveTextContent('High-ranked idea');
  expect(rows[1]).toHaveTextContent('Low-ranked idea');
});

it('renders each idea row as a link to its own ?idea= URL', () => {
  // The whole point of the selection living in the URL: a row is an anchor,
  // so a middle- or cmd-click opens that idea in a new browser tab.
  renderIdeas(
    <IdeasTab
      hypotheses={[
        makeHypothesis({id: 'h-top', title: 'Top idea', elo_rating: 1300}),
        makeHypothesis({id: 'h next', title: 'Next idea', elo_rating: 1200}),
      ]}
      reviews={[]}
    />,
  );

  expect(screen.getByRole('link', {name: /Top idea/})).toHaveAttribute(
    'href',
    '/runs/run-1/ideas?idea=h-top',
  );
  // Ids are encoded, not interpolated raw.
  expect(screen.getByRole('link', {name: /Next idea/})).toHaveAttribute(
    'href',
    '/runs/run-1/ideas?idea=h%20next',
  );
});

it('opens the idea named by the ?idea= param', () => {
  renderIdeas(
    <IdeasTab
      hypotheses={[
        makeHypothesis({
          id: 'h-top',
          title: 'Top idea',
          statement: 'The winning statement.',
          elo_rating: 1300,
        }),
        makeHypothesis({
          id: 'h-second',
          title: 'Second idea',
          statement: 'The runner-up statement.',
          elo_rating: 1200,
        }),
      ]}
      reviews={[]}
    />,
    '/runs/run-1/ideas?idea=h-second',
  );

  // The detail pane follows the URL rather than the default top-ranked pick.
  expect(screen.getByRole('link', {name: /Second idea/})).toHaveAttribute(
    'aria-current',
    'true',
  );
  const detail = screen.getByLabelText('Hypothesis detail');
  expect(within(detail).getByText('Second idea')).toBeInTheDocument();
});

it('flags an evidence-less idea with the "Unverified" chip', () => {
  const {container} = renderIdeas(
    <IdeasTab
      hypotheses={[
        makeHypothesis({
          id: 'grounded',
          title: 'Grounded idea',
          elo_rating: 1300,
          unverified: false,
        }),
        makeHypothesis({
          id: 'latent',
          title: 'Latent idea',
          elo_rating: 1250,
          unverified: true,
        }),
      ]}
      reviews={[]}
    />,
  );
  // Rank-and-publish: both ideas are published and ranked, and only the
  // evidence-less one carries the "Unverified" chip.
  expect(screen.getAllByText('Grounded idea').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Latent idea').length).toBeGreaterThan(0);
  const chips = container.querySelectorAll('.idea-unverified-chip');
  expect(chips).toHaveLength(1);
  expect(chips[0]).toHaveTextContent('Unverified');
});

it('renders reference detail sections without the legacy detail link', () => {
  const reviews: Review[] = [
    {
      id: 1,
      hypothesis_id: 'h1',
      reviewer_agent: 'reflection',
      summary: 'Reasonable.',
      critique: 'Needs a control arm.',
      novelty: 7,
      plausibility: 8,
      testability: 6,
      overall: 7,
    },
  ];
  renderIdeas(
    <IdeasTab
      hypotheses={[makeHypothesis({id: 'h1', title: 'Focusable idea'})]}
      reviews={reviews}
    />,
  );
  expect(screen.getByText('Review summary')).toBeInTheDocument();
  expect(screen.getByText('Full review')).toBeInTheDocument();
  expect(screen.getByText('Reasonable.')).toBeInTheDocument();
  expect(screen.getByText('Needs a control arm.')).toBeInTheDocument();
  expect(screen.queryByText('Full legacy detail')).not.toBeInTheDocument();
});

it('labels an idea with no matches by reason rather than showing 1200', () => {
  // 1200 is where every hypothesis starts, so printing it for an idea the
  // tournament never reached reads as a rating it earned.
  renderIdeas(
    <IdeasTab
      hypotheses={[makeHypothesis({id: 'unplayed', title: 'Never matched'})]}
      reviews={[]}
    />,
  );

  expect(screen.getByText('Unranked')).toBeInTheDocument();
  expect(screen.queryByText(/Elo rating/)).not.toBeInTheDocument();
});

it('distinguishes a disqualified idea from one that never got its turn', () => {
  // Both have no rating, for unrelated reasons: one was withheld from the
  // tournament on the merits, the other simply never played. A single shared
  // label read as "we ran out of time" for ideas that were actually rejected.
  renderIdeas(
    <IdeasTab
      hypotheses={[
        makeHypothesis({
          id: 'blocked',
          title: 'Contradicted',
          status: 'rejected',
        }),
        makeHypothesis({id: 'late', title: 'Made too late'}),
      ]}
      reviews={[]}
    />,
  );

  expect(screen.getByText('Disqualified')).toBeInTheDocument();
  expect(screen.getByText('Unranked')).toBeInTheDocument();
});

it('shows a rating for a disqualified idea that did play before exclusion', () => {
  // Exclusion can follow matches (deep verification undermines an idea after
  // it competed). The score it earned is real and stays visible.
  renderIdeas(
    <IdeasTab
      hypotheses={[
        makeHypothesis({
          id: 'played-then-blocked',
          elo_rating: 1240,
          win_count: 1,
          status: 'rejected',
        }),
      ]}
      reviews={[]}
    />,
  );

  expect(screen.getByText('Elo rating: 1240')).toBeInTheDocument();
  expect(screen.queryByText('Disqualified')).not.toBeInTheDocument();
});
