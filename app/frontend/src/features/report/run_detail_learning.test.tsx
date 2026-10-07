import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {LearningView} from './run_detail_learning';

describe('run detail learning', () => {
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
      retracted: false,
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
      retracted: false,
    },
  ];

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

  it('labels a retracted reference distinctly from a merely unreachable one', () => {
    render(
      <LearningView
        goal="goal"
        evidence={[
          {
            id: 'ev-gone',
            title: 'a source that never resolved',
            source: 'PubMed',
            url: 'https://example.test/gone',
            authors: ['A. Researcher'],
            year: 2025,
            abstract: '',
            available: false,
            retracted: true,
          },
        ]}
      />,
    );

    const pill = screen.getByText('Retracted');
    expect(pill).toBeInTheDocument();
    expect(pill).toHaveAttribute(
      'data-tooltip',
      'This source has been retracted',
    );
    expect(pill).toHaveAccessibleName('This source has been retracted');
    expect(screen.queryByText('Unavailable')).toBeNull();
    expect(screen.queryByRole('link', {name: 'Open'})).toBeNull();
  });
});
