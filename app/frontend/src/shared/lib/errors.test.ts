import {expect, it} from 'vitest';
import {HttpError} from '@/shared/api/runs';
import {errorMessage, httpStatus} from './errors';

it('reads an Error message or falls back', () => {
  expect(errorMessage(new Error('boom'))).toBe('boom');
  expect(errorMessage('plain')).toBe('plain');
  expect(errorMessage(42, 'Could not save.')).toBe('Could not save.');
});

it('reads the status an API error carries', () => {
  expect(httpStatus(new HttpError('nope', 422))).toBe(422);
  expect(httpStatus(new Error('no status'))).toBeUndefined();
});
