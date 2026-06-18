import {describe, expect, it} from 'vitest';
import {inferRunSpec, reviseRunSpec} from './run_spec';

describe('inferRunSpec', () => {
  it('builds a compact standard setup from a research goal', () => {
    const spec = inferRunSpec(
      '  Identify a novel mechanism in cancer signalling.  ',
      'standard',
    );

    expect(spec.goal).toBe('Identify a novel mechanism in cancer signalling.');
    expect(spec.profile).toBe('standard');
    expect(spec.mode).toBe('Standard hypothesis sprint');
    expect(spec.output).toContain('Ranked hypotheses with Elo');
    expect(spec.constraints.join(' ')).toContain('biomedical safety');
    expect(spec.constraints.join(' ')).toContain('causal mechanism');
  });

  it('keeps advanced effort as a simple profile without numeric overrides', () => {
    const spec = inferRunSpec(
      'Investigate cold-stress control of glucose homeostasis.',
      'advanced',
    );

    expect(spec.profile).toBe('advanced');
    expect(spec.mode).toBe('Advanced hypothesis tournament');
    expect(spec.constraints.join(' ')).toContain('deeper tournament');
  });
});

describe('reviseRunSpec', () => {
  it('applies chat edits and mode changes without exposing advanced fields', () => {
    const original = inferRunSpec('Study mitochondrial biogenesis.', 'standard');
    const revised = reviseRunSpec(
      original,
      'Use advanced mode and focus on clinically testable mechanisms.',
    );

    expect(revised.profile).toBe('advanced');
    expect(revised.mode).toBe('Advanced hypothesis tournament');
    expect(revised.constraints.at(-1)).toContain('Apply steering note');
  });

  it('can update the goal through a chat instruction', () => {
    const original = inferRunSpec('Study mitochondrial biogenesis.', 'standard');
    const revised = reviseRunSpec(
      original,
      'Change the goal to identify drug repurposing candidates for TNBC',
    );

    expect(revised.goal).toBe('identify drug repurposing candidates for TNBC');
  });
});
