import {describe, it, expect} from 'vitest';
import {conciseTitle} from './text';

describe('conciseTitle', () => {
  it('returns a short goal unchanged', () => {
    expect(conciseTitle('Cellular aging therapies')).toBe(
      'Cellular aging therapies',
    );
  });

  it('takes the first clause of a multi-clause goal', () => {
    expect(
      conciseTitle('Reversing liver fibrosis; detail the mechanism.'),
    ).toBe('Reversing liver fibrosis');
  });

  it('truncates a long goal on a word boundary with an ellipsis', () => {
    const out = conciseTitle(
      'Identify novel mechanisms of selective autophagy in aging neural tissue.',
    );
    expect(out.endsWith('…')).toBe(true);
    expect(out.length).toBeLessThanOrEqual(53);
    expect(out.startsWith('Identify novel mechanisms')).toBe(true);
    // No dangling short connector word before the ellipsis.
    expect(out).not.toMatch(/\b(in|of|to|a|the)…$/);
  });

  it('falls back for empty input', () => {
    expect(conciseTitle('')).toBe('Untitled session');
    expect(conciseTitle('   ')).toBe('Untitled session');
  });
});
