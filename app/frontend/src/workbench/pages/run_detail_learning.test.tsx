import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {LearningView} from './run_detail_learning';

const evidence = [
  {
    id: 'ev-1',
    title: 'mitochondrial feedback in cold stress',
    source: 'PubMed',
    url: 'https://example.test/pubmed',
    authors: ['A. Researcher', 'B. Scientist'],
    year: 2025,
    abstract:
      'BACKGROUND: Cold stress changes glucose homeostasis. METHODS: Cells ' +
      'were profiled with mitochondrial assays.',
    available: true,
  },
  {
    id: 'ev-2',
    title: 'synaptic pruning mechanisms',
    source: 'Preprint',
    url: '',
    authors: ['C. Author'],
    year: null,
    abstract: 'Microglia remodel synapses during neuroinflammation.',
    available: true,
  },
];

describe('LearningView', () => {
  it('renders learning sections, detail, and searchable refs', () => {
    render(
      <LearningView
        goal="Investigate glucose homeostasis under cold stress."
        evidence={evidence}
      />,
    );

    expect(
      screen.getByRole('heading', {name: 'Knowledge Base'}),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        name: 'Mitochondrial Feedback in Cold Stress',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('Background')).toBeInTheDocument();

    const openLink = screen.getByRole('link', {name: 'Open'});
    expect(openLink).toHaveAttribute('href', 'https://example.test/pubmed');
    expect(openLink).toHaveClass('reference-open-pill', 'rounded-full');

    fireEvent.click(screen.getAllByRole('button', {name: /Show more/i})[0]);

    expect(
      screen.getByText(/Source context: PubMed, 2025/),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Search references'), {
      target: {value: 'synaptic'},
    });

    expect(screen.getByText('synaptic pruning mechanisms')).toBeInTheDocument();
    expect(
      screen.queryByText('mitochondrial feedback in cold stress'),
    ).toBeNull();
  });
});
