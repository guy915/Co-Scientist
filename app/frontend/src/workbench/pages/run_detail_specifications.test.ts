import {describe, expect, it} from 'vitest';
import type {RunAttribute} from '@/api/runs';
import {attributeDisplayString} from './run_detail_specifications';

describe('attributeDisplayString', () => {
  it('passes a legacy free-prose string through unchanged', () => {
    expect(attributeDisplayString('Mechanistically specific')).toBe(
      'Mechanistically specific',
    );
  });

  it('renders a scaled axis with every anchor point', () => {
    const item: RunAttribute = {
      name: 'Mechanistic specificity',
      scale: {
        '1': 'Vague or hand-wavy mechanism',
        '3': 'Plausible mechanism with some unexplained steps',
        '5': 'Precise, causally complete mechanism',
      },
    };
    expect(attributeDisplayString(item)).toBe(
      'Mechanistic specificity: 1-5 scale (1: Vague or hand-wavy ' +
        'mechanism, 3: Plausible mechanism with some unexplained steps, ' +
        '5: Precise, causally complete mechanism)',
    );
  });

  it('renders a scaled axis that omits the midpoint anchor', () => {
    const item: RunAttribute = {
      name: 'Human Relevance',
      scale: {
        '1': 'Based purely on murine or non-liver models',
        '5': 'Strong basis in human liver data',
      },
    };
    expect(attributeDisplayString(item)).toBe(
      'Human Relevance: 1-5 scale (1: Based purely on murine or ' +
        'non-liver models, 5: Strong basis in human liver data)',
    );
  });

  it('renders a categorical axis with the published "or" punctuation', () => {
    const item: RunAttribute = {
      name: 'Target Area',
      values: [
        'Epigenetics',
        'Stellate Cell Biology',
        'Stromal-Immune Crosstalk',
      ],
    };
    expect(attributeDisplayString(item)).toBe(
      'Target Area (Epigenetics, Stellate Cell Biology, or ' +
        'Stromal-Immune Crosstalk)',
    );
  });

  it('falls back to the bare name for a malformed dict item', () => {
    // Neither `scale` nor `values` -- shouldn't happen through the cleaned
    // backend shape, but the renderer must not throw on it.
    const malformed = {name: 'Impact'} as unknown as RunAttribute;
    expect(attributeDisplayString(malformed)).toBe('Impact');
  });
});
