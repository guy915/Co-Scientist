import {describe, expect, it} from 'vitest';
import {activeSuggestions} from './chat_home_stage';

describe('activeSuggestions', () => {
  it('returns SBI suggestions for sbi_ucd', () => {
    expect(activeSuggestions('sbi_ucd')[0].preview).toMatch(/MAPK/i);
  });

  it('returns default suggestions otherwise', () => {
    expect(activeSuggestions('general')[0].preview).toMatch(/glioblastoma/i);
    expect(activeSuggestions(null)[0].preview).toMatch(/glioblastoma/i);
  });
});
