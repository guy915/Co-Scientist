// Degraded-section notices on the Summary tab (L7): a report section the
// engine could not generate after repeated attempts says so, instead of
// rendering blank (or worse, the in-flight "appears after synthesis" promise
// on a run that already finished).
import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {ResearchOverviewView} from './run_detail_overview';
import {makeReport, makeRun} from './run_detail_overview_test_support';

const NOTICE = 'This section could not be generated after repeated attempts.';

function renderWithReport(payloadOverrides: Parameters<typeof makeReport>[0]) {
  render(
    <ResearchOverviewView
      run={makeRun()}
      report={makeReport(payloadOverrides)}
      hypotheses={[]}
      matches={[]}
    />,
  );
}

it('labels a degraded research overview instead of the in-flight promise', () => {
  renderWithReport({
    degraded_sections: ['research_overview'],
    research_overview: {},
  });

  expect(screen.getByText(NOTICE)).toBeInTheDocument();
  expect(
    screen.queryByText(/appears after Co-Scientist finishes/),
  ).not.toBeInTheDocument();
});

it('keeps the in-flight placeholder when nothing degraded', () => {
  renderWithReport({research_overview: {}});

  expect(
    screen.getByText(/appears after Co-Scientist finishes/),
  ).toBeInTheDocument();
  expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
});

it('flags agent insights when the meta-review degraded', () => {
  renderWithReport({degraded_sections: ['meta_review']});

  expect(
    screen.getByRole('heading', {name: 'Agent Insights'}),
  ).toBeInTheDocument();
  expect(screen.getByText(NOTICE)).toBeInTheDocument();
});

it('prefers real overview content over the notice when both exist', () => {
  // A partial synthesis that still carries a summary renders the summary;
  // the notice is for sections left blank.
  renderWithReport({
    degraded_sections: ['research_overview'],
    research_overview: {overview: {summary: 'A partial synthesis.'}},
  });

  expect(screen.getByText('A partial synthesis.')).toBeInTheDocument();
  expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
});
