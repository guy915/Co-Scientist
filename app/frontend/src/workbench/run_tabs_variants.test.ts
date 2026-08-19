import {describe, expect, it} from 'vitest';
import {normalizeTab, tabsForRun} from './run_tabs';

describe('tabsForRun', () => {
  it('hides the variants tab on a run that has no programs', () => {
    // An always-empty tab is indistinguishable from a broken one.
    expect(tabsForRun(false)).not.toContain('variants');
  });

  it('shows it on a discovery run', () => {
    expect(tabsForRun(true)).toContain('variants');
  });

  it('keeps the other tabs in their existing order', () => {
    expect(tabsForRun(false)).toEqual([
      'details',
      'learning',
      'overview',
      'ideas',
    ]);
  });

  it('hides the hypothesis tabs on a discovery run', () => {
    // It generates no ideas and reads no literature, so both would be
    // permanently empty -- the same defect as an always-empty Variants
    // tab, in the other direction.
    expect(tabsForRun(true)).toEqual(['details', 'overview', 'variants']);
  });

  it('resolves the variants route and its alias', () => {
    expect(normalizeTab('variants')).toBe('variants');
    expect(normalizeTab('programs')).toBe('variants');
  });
});
