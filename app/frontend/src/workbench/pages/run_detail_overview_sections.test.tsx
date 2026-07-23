import {screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {renderFullReport} from './run_detail_overview_test_support';

it('renders the synthesized summary and idea buckets from the report', () => {
  renderFullReport();

  expect(
    screen.getByText('A synthesized summary of the research.'),
  ).toBeInTheDocument();
  expect(screen.getByText('High Potential')).toBeInTheDocument();
  expect(screen.getByText('Non-Viable')).toBeInTheDocument();
  expect(screen.getByText('Verified ideas')).toBeInTheDocument();
  expect(screen.getByText('Sources Analyzed')).toBeInTheDocument();
  expect(screen.getByText('11')).toBeInTheDocument();
});

it('renders the research directions with their suggested experiments', () => {
  renderFullReport();

  expect(
    screen.getByRole('heading', {name: 'Research directions'}),
  ).toBeInTheDocument();
  expect(screen.getByText('Direction one')).toBeInTheDocument();
  expect(screen.getByText('It matters because X.')).toBeInTheDocument();
  expect(screen.getByText('Experiment A')).toBeInTheDocument();
  expect(screen.getByText('Experiment B')).toBeInTheDocument();
  // Second direction has no suggested experiments, so no list under it.
  expect(
    screen.getByText('Direction two (no experiments)'),
  ).toBeInTheDocument();
});

it('renders the specific aims and research contacts', () => {
  renderFullReport();

  expect(
    screen.getByRole('heading', {name: 'Specific aims'}),
  ).toBeInTheDocument();
  expect(screen.getByText('An introduction to the aims.')).toBeInTheDocument();
  expect(screen.getByText('Aim 1: Do the thing')).toBeInTheDocument();
  expect(screen.getByText('Because reasons.')).toBeInTheDocument();
  expect(screen.getByText('Via this approach.')).toBeInTheDocument();
  expect(screen.getByText('The impact statement.')).toBeInTheDocument();
  expect(
    screen.getByRole('heading', {name: 'Research contacts'}),
  ).toBeInTheDocument();
  expect(screen.getByText('Ada Researcher')).toBeInTheDocument();
  expect(
    screen.getByRole('link', {name: 'Evidence: A fibrosis study'}),
  ).toHaveAttribute('href', 'https://pubmed.ncbi.nlm.nih.gov/123/');
});

it('renders the winning-ideas leaderboard and closing stats', () => {
  renderFullReport();

  expect(
    screen.getByRole('heading', {name: 'Winning ideas'}),
  ).toBeInTheDocument();
  expect(screen.getByText('Leaderboard idea')).toBeInTheDocument();
  expect(screen.getByText('Elo rating: 1735')).toBeInTheDocument();

  expect(
    screen.getByText(
      new RegExp(
        'A total of 2 ideas were explored over 3 hours with the highest ' +
          'Elo rating of 1735 points and a total of 3 matches were ' +
          'played\\.',
      ),
    ),
  ).toBeInTheDocument();
});
