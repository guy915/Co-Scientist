import {describe, expect, it} from 'vitest';
import {SUGGESTIONS} from './chat_home_stage';

describe('SUGGESTIONS', () => {
  it('offers the default set of home suggestions', () => {
    expect(SUGGESTIONS[0].preview).toMatch(/glioblastoma/i);
  });
});
