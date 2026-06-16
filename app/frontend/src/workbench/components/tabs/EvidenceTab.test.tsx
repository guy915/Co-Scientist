/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {EvidenceTab} from './EvidenceTab';
import type {CitationRow, Evidence} from '@/api/runs';

function makeEvidence(over: Partial<Evidence> = {}): Evidence {
  return {
    id: 'ev1',
    title: 'CRISPR base editing in primary T cells',
    source: 'PubMed',
    url: 'https://pubmed.example/1',
    authors: ['Doe J', 'Roe A', 'Lee K', 'Park S'],
    year: 2023,
    abstract: 'A study of base-editing efficiency.',
    available: true,
    ...over,
  };
}

describe('EvidenceTab', () => {
  it('shows the empty state when no evidence was retrieved', () => {
    render(<EvidenceTab evidence={[]} citations={[]} />);
    expect(
      screen.getByText('No evidence retrieved for this run.'),
    ).toBeInTheDocument();
  });

  it('renders an evidence row with its title, authors, and abstract', () => {
    render(<EvidenceTab evidence={[makeEvidence()]} citations={[]} />);
    expect(
      screen.getByText('CRISPR base editing in primary T cells'),
    ).toBeInTheDocument();
    // First three authors then "et al." for a fourth, plus year and source.
    expect(
      screen.getByText(/Doe J, Roe A, Lee K et al\. · 2023 · PubMed/),
    ).toBeInTheDocument();
    expect(
      screen.getByText('A study of base-editing efficiency.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', {name: 'Open'})).toHaveAttribute(
      'href',
      'https://pubmed.example/1',
    );
  });

  it('renders citation-state filter buttons with their totals', () => {
    const citations: CitationRow[] = [
      {
        id: 1,
        hypothesis_id: 'h1',
        evidence_id: 'ev1',
        claim: 'Base editing raises efficiency.',
        state: 'verified',
      },
      {
        id: 2,
        hypothesis_id: 'h1',
        evidence_id: 'ev1',
        claim: 'Off-target effects remain low.',
        state: 'partial',
      },
    ];
    render(<EvidenceTab evidence={[makeEvidence()]} citations={citations} />);
    // "Verified"/"Partial" appear on both the filter button and the citation
    // chip, so multiple matches are expected.
    expect(screen.getAllByText('Verified').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Partial').length).toBeGreaterThanOrEqual(2);
    // The four state filters are all active (aria-pressed) by default and each
    // surfaces its citation total.
    const filters = screen
      .getAllByRole('button')
      .filter(b => b.getAttribute('aria-pressed') !== null);
    expect(filters).toHaveLength(4);
    expect(filters.every(b => b.getAttribute('aria-pressed') === 'true')).toBe(
      true,
    );
    // The Verified filter button tallies its one citation.
    const verifiedFilter = screen
      .getAllByRole('button')
      .find(
        b =>
          b.getAttribute('aria-pressed') !== null &&
          /Verified/.test(b.textContent ?? ''),
      );
    expect(verifiedFilter).toBeDefined();
    expect(verifiedFilter).toHaveTextContent('1');
  });
});
