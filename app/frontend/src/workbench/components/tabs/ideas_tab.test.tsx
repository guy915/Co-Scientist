import {stubViewport} from '@/browser_test_support';
import type {ReactElement} from 'react';
import {afterEach, it, expect, vi} from 'vitest';
import {render, screen, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {IdeasTab} from './ideas_tab';
import type {Hypothesis, Review} from '@/api/runs';
import {makeHypothesis} from '@/test_fixtures';

function renderIdeas(ui: ReactElement, path = '/runs/run-1/ideas') {
  return render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

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
  expect(screen.getByText('Elo rating: 1300')).toBeInTheDocument();
  expect(screen.queryByText('80% wins')).not.toBeInTheDocument();

  const rows = screen.getAllByRole('listitem');
  expect(rows[0]).toHaveTextContent('High-ranked idea');
  expect(rows[1]).toHaveTextContent('Low-ranked idea');
});

it('renders each idea row as a link to its own ?idea= URL', () => {
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

  expect(screen.getByRole('link', {name: /Second idea/})).toHaveAttribute(
    'aria-current',
    'page',
  );
  const detail = screen.getByLabelText('Hypothesis detail');
  expect(within(detail).getByText('Second idea')).toBeInTheDocument();
  expect(screen.getByRole('link', {name: /Second idea/})).toHaveAttribute(
    'aria-controls',
    detail.id,
  );
  expect(detail.id).toBeTruthy();
  expect(screen.getByRole('link', {name: /Top idea/})).not.toHaveAttribute(
    'aria-controls',
  );
});

it('flags an evidence-less idea Unverified and a probe-falsified one Undermined, showing only the stronger caution when both', () => {
  // Contradictory evidence and absent support are different findings; two
  // chips would wrap the row, so the stronger caution wins.
  const {container} = renderIdeas(
    <IdeasTab
      hypotheses={[
        makeHypothesis({
          id: 'grounded',
          title: 'Grounded idea',
          elo_rating: 1300,
        }),
        makeHypothesis({
          id: 'latent',
          title: 'Latent idea',
          elo_rating: 1250,
          unverified: true,
        }),
        makeHypothesis({
          id: 'doubted',
          title: 'Doubted idea',
          elo_rating: 1400,
          verification_verdict: 'undermined',
        }),
        makeHypothesis({
          id: 'both',
          title: 'Doubly flagged idea',
          elo_rating: 1165,
          unverified: true,
          verification_verdict: 'undermined',
        }),
      ]}
      reviews={[]}
    />,
  );

  const chips = (selector: string) =>
    [...container.querySelectorAll(selector)].map(
      chip => chip.closest('a')?.textContent,
    );
  expect(chips('.idea-unverified-chip')).toEqual([
    expect.stringContaining('Latent idea'),
  ]);
  expect(chips('.idea-undermined-chip')).toEqual([
    expect.stringContaining('Doubted idea'),
    expect.stringContaining('Doubly flagged idea'),
  ]);
  expect(
    container.querySelectorAll('.idea-rank-head .idea-unverified-chip'),
  ).toHaveLength(1);
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
  expect(screen.getByText('Review critiques')).toBeInTheDocument();
  expect(screen.getByText('Reflection review')).toBeInTheDocument();
  expect(screen.getByText('Reasonable.')).toBeInTheDocument();
  expect(screen.getByText('Needs a control arm.')).toBeInTheDocument();
  expect(screen.queryByText('Full legacy detail')).not.toBeInTheDocument();
});

it('labels an idea with no matches by reason rather than showing 1200', () => {
  // Initial Elo is not an earned tournament rating.
  renderIdeas(
    <IdeasTab
      hypotheses={[makeHypothesis({id: 'unplayed', title: 'Never matched'})]}
      reviews={[]}
    />,
  );

  expect(screen.getByText('Unranked')).toBeInTheDocument();
  expect(screen.queryByText(/Elo rating/)).not.toBeInTheDocument();
});

it('leaves withdrawn ideas out of the list entirely', () => {
  renderIdeas(
    <IdeasTab
      hypotheses={[
        makeHypothesis({id: 'kept', title: 'Still standing', win_count: 1}),
        makeHypothesis({
          id: 'rejected',
          title: 'Ruled out on the merits',
          status: 'rejected',
        }),
        makeHypothesis({
          id: 'duplicate',
          title: 'Folded into another',
          status: 'duplicate',
        }),
      ]}
      reviews={[]}
    />,
  );

  expect(screen.getAllByText('Still standing').length).toBeGreaterThan(0);
  expect(screen.queryByText('Ruled out on the merits')).toBeNull();
  expect(screen.queryByText('Folded into another')).toBeNull();
});

it('says so when every idea a run explored was withdrawn', () => {
  // An entirely excluded pool differs from a run that generated nothing.
  renderIdeas(
    <IdeasTab
      hypotheses={[makeHypothesis({id: 'gone', status: 'duplicate'})]}
      reviews={[]}
    />,
  );

  expect(
    screen.getByText(/was ruled out or folded into another/),
  ).toBeVisible();
});

// The titlebar is the mobile detail view's only escape; expose that
// relationship accessibly.
it('tells the reader the titlebar Back arrow returns to the ranked list', () => {
  stubViewport(true);
  renderIdeas(
    <IdeasTab
      hypotheses={[makeHypothesis({id: 'h-top', title: 'Top idea'})]}
      reviews={[]}
    />,
    '/runs/run-1/ideas?idea=h-top',
  );

  expect(screen.getByText(/Back button in the title bar/i)).toBeInTheDocument();
});

it('omits the back hint when the mobile list has no idea open', () => {
  stubViewport(true);
  renderIdeas(
    <IdeasTab
      hypotheses={[makeHypothesis({id: 'h-top', title: 'Top idea'})]}
      reviews={[]}
    />,
  );

  expect(
    screen.queryByText(/Back button in the title bar/i),
  ).not.toBeInTheDocument();
});

// Fixed list and rail widths leave detail unreadable below the split-grid
// boundary.
it('stacks the split grid below the width its columns actually need', () => {
  const {container} = renderIdeas(
    <IdeasTab
      hypotheses={[makeHypothesis({id: 'h-top', title: 'Top idea'})]}
      reviews={[]}
    />,
  );

  const grid = container.querySelector('.idea-split-grid');
  expect(grid?.className).toContain('max-[1023px]:grid-cols-1');
  expect(grid?.className).not.toContain('720px');
  expect(grid?.className).not.toContain('max-[700px]:grid-cols-1');
});
