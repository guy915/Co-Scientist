// The run-level retrieval notice on the Summary tab: a run that could
// reach no literature source says so at the top of its report. Unlike a
// degraded section, nothing else in the output hints at it -- the ideas,
// reviews and tournament all look exactly like a healthy run's.
import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {ResearchOverviewView} from './run_detail_overview';
import {makeReport, makeRun} from './run_detail_overview_test_support';

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

it('says what a run without any source lost, and what it had left', () => {
  renderWithReport({
    retrieval_degradation: {
      reason: 'mcp_unreachable',
      lost: ['literature_review', 'deep_research'],
      floor: 'none',
    },
  });

  expect(
    screen.getByText(/No literature source was reachable during this run/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/the literature review and follow-up research/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Nothing else was available to search/),
  ).toBeInTheDocument();
});

it('names the run’s own documents when those were the floor', () => {
  renderWithReport({
    retrieval_degradation: {
      reason: 'mcp_unreachable',
      lost: ['literature_review'],
      floor: 'run_attachments',
    },
  });

  expect(
    screen.getByText(/Only the documents attached to this run/),
  ).toBeInTheDocument();
});

it('drops a capability name it has no words for', () => {
  // An engine that grows a new one should not print its identifier at a
  // reader; the sentence is still true without it.
  renderWithReport({
    retrieval_degradation: {
      reason: 'mcp_unreachable',
      lost: ['literature_review', 'some_future_thing'],
      floor: 'none',
    },
  });

  expect(screen.queryByText(/some_future_thing/)).not.toBeInTheDocument();
  expect(
    screen.getByText(/ran without the literature review/),
  ).toBeInTheDocument();
});

it('says nothing on a run that retrieved normally', () => {
  renderWithReport({});

  expect(
    screen.queryByText(/No literature source was reachable/),
  ).not.toBeInTheDocument();
});
