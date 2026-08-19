import {describe, expect, it} from 'vitest';
import {directionArrow, formatMeasured, measuredValue} from './objectives';

const SECONDS = {metric: 'seconds', direction: 'minimize'};
const SCORE = {metric: 'score', direction: 'maximize'};

describe('measuredValue', () => {
  it('un-negates a minimized metric', () => {
    // Stored so higher is always better, which holds a minimized metric
    // negated; printed straight it reports 1.9 seconds as -1.9.
    expect(measuredValue(-1.9, SECONDS)).toBe(1.9);
  });

  it('leaves a maximized one alone', () => {
    expect(measuredValue(8.25, SCORE)).toBe(8.25);
  });

  it('leaves a value alone when the objective is unknown', () => {
    // Without a direction there is nothing to undo, and guessing would
    // flip half the numbers on a surface that has not loaded its
    // objectives yet.
    expect(measuredValue(-1.9)).toBe(-1.9);
  });
});

describe('formatMeasured', () => {
  it('shows an unscored attempt as a dash, never a zero', () => {
    expect(formatMeasured(null)).toBe('—');
    expect(formatMeasured(0)).toBe('0');
  });

  it('compacts an absurd magnitude instead of overflowing its tile', () => {
    // A search is free to find one: an early run scored 9.33e+157, and
    // plain rounding rendered that as a 160-character string.
    expect(formatMeasured(9.332621544394415e157)).toBe('9.33e+157');
    expect(formatMeasured(0.0000001)).toBe('1.00e-7');
  });

  it('keeps an ordinary score readable', () => {
    expect(formatMeasured(8.25)).toBe('8.25');
    expect(formatMeasured(1000.5)).toBe('1000.5');
  });

  it('reads a minimized metric in its own units', () => {
    expect(formatMeasured(-1.9, SECONDS)).toBe('1.9');
  });
});

describe('directionArrow', () => {
  it('points the way better lies', () => {
    expect(directionArrow(SECONDS)).toBe('↓');
    expect(directionArrow(SCORE)).toBe('↑');
  });
});
