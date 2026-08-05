import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import type {AgentInsights} from '@/api/runs';
import {AgentInsightsSection} from './run_detail_insights';

function makeInsights(overrides: Partial<AgentInsights> = {}): AgentInsights {
  return {
    key_findings: ['Feedback is causal.'],
    uncertainties: [],
    contradictions: [],
    recommended_directions: [],
    next_experiments: [],
    ...overrides,
  };
}

it('renders each recommendation as its three named fields', () => {
  render(
    <AgentInsightsSection
      insights={makeInsights({
        recommended_directions: [
          {
            focus_area: 'Receptor pharmacology',
            recommendation: 'Measure binding directly by SPR.',
            justification: 'The claimed affinity is unproven.',
          },
        ],
      })}
    />,
  );

  expect(
    screen.getByRole('heading', {name: 'Recommended directions'}),
  ).toBeInTheDocument();
  expect(screen.getByText('Receptor pharmacology')).toBeInTheDocument();
  expect(
    screen.getByText('Measure binding directly by SPR.'),
  ).toBeInTheDocument();
  expect(
    screen.getByText('The claimed affinity is unproven.'),
  ).toBeInTheDocument();
  // The three fields must never be flattened back into an object repr.
  expect(document.body.textContent).not.toContain("{'focus_area'");
  expect(document.body.textContent).not.toContain('"focus_area"');
});

it('hides a section whose entries are all blank', () => {
  // The list length alone used to decide whether a heading rendered, so a list
  // of empty strings produced a heading with nothing beneath it.
  render(
    <AgentInsightsSection
      insights={makeInsights({contradictions: ['', '   ']})}
    />,
  );

  expect(
    screen.queryByRole('heading', {name: 'Contradictions'}),
  ).not.toBeInTheDocument();
  expect(screen.getByRole('heading', {name: 'Key findings'})).toBeVisible();
});

it('still renders a recommendation from an older persisted report', () => {
  // Report payloads are stored, so reports written before recommendations
  // kept their three fields hold one flattened string per entry.
  render(
    <AgentInsightsSection
      insights={makeInsights({
        recommended_directions: ['Measure binding directly by SPR.'],
      })}
    />,
  );

  expect(
    screen.getByText('Measure binding directly by SPR.'),
  ).toBeInTheDocument();
});

it('drops a recommendation with no focus area and no advice', () => {
  render(
    <AgentInsightsSection
      insights={makeInsights({
        recommended_directions: [
          {focus_area: '', recommendation: '', justification: 'Orphaned.'},
        ],
      })}
    />,
  );

  expect(
    screen.queryByRole('heading', {name: 'Recommended directions'}),
  ).not.toBeInTheDocument();
});

it('flags a meta-review that degraded to a fallback', () => {
  // L7: the meta-review-derived lists are blank after a fallback, so the
  // section must say generation failed instead of showing silence.
  render(<AgentInsightsSection insights={makeInsights()} degraded />);

  expect(
    screen.getByText(
      'This section could not be generated after repeated attempts.',
    ),
  ).toBeInTheDocument();
});

it('renders the degradation notice even without any insights payload', () => {
  render(<AgentInsightsSection insights={undefined} degraded />);

  expect(
    screen.getByRole('heading', {name: 'Agent Insights'}),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      'This section could not be generated after repeated attempts.',
    ),
  ).toBeInTheDocument();
});

it('shows no degradation notice for a clean run', () => {
  render(<AgentInsightsSection insights={makeInsights()} />);

  expect(
    screen.queryByText(
      'This section could not be generated after repeated attempts.',
    ),
  ).not.toBeInTheDocument();
});
