import type {ReactElement} from 'react';
import {afterEach, it, expect, vi} from 'vitest';
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

/**
 * Pins the viewport to one side of the phone breakpoint for a single test.
 *
 * `useIsMobile` reads `matchMedia`, which jsdom does not implement, so an
 * unstubbed test is always "desktop" -- which would let a mobile-only
 * assertion pass for the wrong reason. Mirrors the stub in
 * run_detail.test.tsx.
 *
 * @param mobile Whether the viewport should match the phone breakpoint.
 */
function stubViewport(mobile: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: mobile,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  );
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
  // "page" (not "true") is the accurate value here: the row is a real link
  // to the currently-shown page-within-a-page, same as the report tab strip.
  expect(screen.getByRole('link', {name: /Second idea/})).toHaveAttribute(
    'aria-current',
    'page',
  );
  const detail = screen.getByLabelText('Hypothesis detail');
  expect(within(detail).getByText('Second idea')).toBeInTheDocument();
  // The selected row states the relationship explicitly: it points at the
  // detail pane it drives via aria-controls, rather than leaving the two
  // regions with no stated connection.
  expect(screen.getByRole('link', {name: /Second idea/})).toHaveAttribute(
    'aria-controls',
    detail.id,
  );
  expect(detail.id).toBeTruthy();
  expect(screen.getByRole('link', {name: /Top idea/})).not.toHaveAttribute(
    'aria-controls',
  );
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

it('flags a probe-falsified idea "Undermined", apart from "Unverified"', () => {
  // Deep verification stopped withholding these ideas, so the chip is now
  // the only thing telling a reader that evidence was found *against* this
  // one -- a different fact from "no supporting evidence was found", which
  // is why they are separate chips rather than one shared caution.
  const {container} = renderIdeas(
    <IdeasTab
      hypotheses={[
        makeHypothesis({
          id: 'sound',
          title: 'Sound idea',
          elo_rating: 1300,
          verification_verdict: 'holds',
        }),
        makeHypothesis({
          id: 'doubted',
          title: 'Doubted idea',
          elo_rating: 1400,
          verification_verdict: 'undermined',
        }),
      ]}
      reviews={[]}
    />,
  );
  expect(screen.getAllByText('Doubted idea').length).toBeGreaterThan(0);
  const chips = container.querySelectorAll('.idea-undermined-chip');
  expect(chips).toHaveLength(1);
  expect(chips[0]).toHaveTextContent('Undermined');
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
  // The reviewer's own label heads its critique (finding D13).
  expect(screen.getByText('Reflection review')).toBeInTheDocument();
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

it('leaves withdrawn ideas out of the list entirely', () => {
  // The Goal Report already excludes both, so listing them here made the two
  // surfaces disagree, and it padded a ranking with entries that were
  // explicitly not ranked. The run's "ideas explored" count still covers them.
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

  // The surviving idea heads the list and fills the detail pane beside it.
  expect(screen.getAllByText('Still standing').length).toBeGreaterThan(0);
  expect(screen.queryByText('Ruled out on the merits')).toBeNull();
  expect(screen.queryByText('Folded into another')).toBeNull();
});

it('says so when every idea a run explored was withdrawn', () => {
  // Distinct from "nothing generated yet": reporting the second as the first
  // reads as a run that produced nothing at all.
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

// MobileIdeaView renders no back control of its own; the titlebar's Back
// arrow is retargeted to the ranked list while an idea is open on phone (see
// reportBackTarget in run_detail_shell.tsx), but nothing said so from inside
// this view itself. A screen-reader user landing here has no way to
// discover that escape without this hint.
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

// The list view (nothing selected yet) carries no such hint -- there is
// nothing to escape from.
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

// The split grid stacks on its own boundary, NOT the phone breakpoint. Its
// three columns have a 656px non-shrinkable floor (24rem list + 17rem rail),
// so the detail column -- the content the reader came for -- gets only what
// is left over. Measured in a browser at the 720px this used to carry, and
// at the 700px that replaced it: the detail rendered 0px wide at a 701px
// viewport and 56px at 721px, i.e. the split could not show its own content
// anywhere near either number. It first becomes readable around 1024px,
// which is where the columns now stack below.
it('stacks the split grid below the width its columns actually need', () => {
  const {container} = renderIdeas(
    <IdeasTab
      hypotheses={[makeHypothesis({id: 'h-top', title: 'Top idea'})]}
      reviews={[]}
    />,
  );

  const grid = container.querySelector('.idea-split-grid');
  expect(grid?.className).toContain('max-[1023px]:grid-cols-1');
  // Neither of the two boundaries that left this band unreadable.
  expect(grid?.className).not.toContain('720px');
  expect(grid?.className).not.toContain('max-[700px]:grid-cols-1');
});
