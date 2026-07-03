import {describe, expect, it} from 'vitest';
import {inferRunSpec, reviseRunSpec} from './run_spec';

describe('inferRunSpec', () => {
  it('builds a compact canonical setup from a research goal', () => {
    const spec = inferRunSpec(
      '  Identify a novel mechanism in cancer signalling.  ',
    );

    expect(spec.goal).toBe('Identify a novel mechanism in cancer signalling.');
    expect(spec.mode).toBe('Hypothesis tournament');
    expect(spec.output).toContain('Ranked hypotheses with Elo');
    expect(spec.constraints.join(' ')).toContain('biomedical safety');
    expect(spec.constraints.join(' ')).toContain('causal mechanism');
  });

  it('uses constraints for tournament ranking and evolution', () => {
    const spec = inferRunSpec(
      'Investigate cold-stress control of glucose homeostasis.',
    );

    expect(spec.mode).toBe('Hypothesis tournament');
    expect(spec.constraints.join(' ')).toContain('tournament ranking');
  });
});

describe('reviseRunSpec', () => {
  it('applies chat edits while preserving the canonical setup', () => {
    const original = inferRunSpec('Study mitochondrial biogenesis.');
    const revised = reviseRunSpec(
      original,
      'Focus on clinically testable mechanisms.',
    );

    expect(revised.mode).toBe('Hypothesis tournament');
    expect(revised.constraints.at(-1)).toContain('Apply steering note');
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
