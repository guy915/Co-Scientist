import {expect, it} from 'vitest';
import {displayTitle} from './titles';

it('prefers a trimmed stored title', () => {
  expect(displayTitle('  Named  ', 'goal')).toBe('Named');
});

it('falls back to the shortened goal for a blank title', () => {
  expect(displayTitle('   ', 'Find a drug', goal => `short:${goal}`)).toBe(
    'short:Find a drug',
  );
});
