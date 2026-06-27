import {describe, expect, it} from 'vitest';
import {inferRunSpec, reviseRunSpec} from './run_spec';

describe('inferRunSpec', () => {
  it('builds a compact canonical setup from a research goal', () => {
    const spec = inferRunSpec(
      '  Identify a novel mechanism in cancer signalling.  ',
    );

    expect(spec.goal).toBe('Identify a novel mechanism in cancer signalling.');
    expect(spec.focus).toBe('balance');
    expect(spec.tier).toBe('standard');
    expect(spec.requirements.join(' ')).toContain('biomedical safety');
    expect(spec.requirements.join(' ')).toContain('causal mechanism');
    expect(spec.attributes.join(' ')).toContain('Translationally plausible');
  });

  it('uses requirements for tournament ranking and evolution', () => {
    const spec = inferRunSpec(
      'Investigate cold-stress control of glucose homeostasis.',
    );

    expect(spec.criteria.join(' ')).toContain('Measurable biological readout');
    expect(spec.requirements.join(' ')).toContain('tournament ranking');
  });
});

describe('reviseRunSpec', () => {
  it('applies chat edits while preserving the canonical setup', () => {
    const original = inferRunSpec('Study mitochondrial biogenesis.');
    const revised = reviseRunSpec(
      original,
      'Focus on clinically testable mechanisms.',
    );

    expect(revised.focus).toBe('balance');
    expect(revised.tier).toBe('standard');
    expect(revised.requirements.at(-1)).toContain('Apply steering note');
  });

  it('can update the goal through a chat instruction', () => {
    const original = inferRunSpec('Study mitochondrial biogenesis.');
    const revised = reviseRunSpec(
      original,
      'Change the goal to identify drug repurposing candidates for TNBC',
    );

    expect(revised.goal).toBe('identify drug repurposing candidates for TNBC');
  });
});
