// One place that undoes the sign correction on an objective's value.
//
// Scores are stored so that higher is always better on every axis,
// which means a minimized metric is held negated. Every surface that
// prints one has to undo that, and each doing it its own way is how the
// Variants table came to report "-1.9" for the 1.9 seconds the report
// prints as 1.9 -- two surfaces disagreeing about one number.

import type {DiscoveryObjective} from '@/api/runs';

/** The direction that means a lower measurement is better. */
export const MINIMIZE = 'minimize';

/**
 * A sign-corrected value in the units it was measured in.
 *
 * @param value The stored, sign-corrected value.
 * @param objective The objective it belongs to; undefined leaves the
 *   value alone, since without a direction there is nothing to undo.
 * @returns The measured value.
 */
export function measuredValue(
  value: number,
  objective?: DiscoveryObjective,
): number {
  return objective?.direction === MINIMIZE ? -value : value;
}

/**
 * A sign-corrected value rendered for display, rounded to 3 decimals.
 *
 * @param value The stored value, or null when the attempt has no score.
 * @param objective The objective it belongs to, if known.
 * @returns The rounded measured value, or an em dash. A dash is never a
 *   zero: no position in the ordering and a real score of zero are
 *   different facts, and rendering them alike implies a crashed attempt
 *   was merely a bad one.
 */
export function formatMeasured(
  value: number | null,
  objective?: DiscoveryObjective,
): string {
  if (value === null) return '—';
  return compactNumber(measuredValue(value, objective));
}

// Magnitudes outside this band print in exponent form. A search is free
// to find something absurd -- an early run scored 9.33e+157 -- and the
// plain rounding this used to do rendered that as a 160-character string
// that broke out of its tile. Three significant figures is what a score
// tile can show; the exact value stays on the variant.
const BIG = 1e6;
const SMALL = 1e-4;

function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  const magnitude = Math.abs(value);
  if (magnitude !== 0 && (magnitude >= BIG || magnitude < SMALL)) {
    return value.toExponential(2);
  }
  return String(Math.round(value * 1000) / 1000);
}

/**
 * The arrow marking which way is better for an objective.
 *
 * @param objective The objective to label.
 * @returns '↓' when lower is better, '↑' otherwise.
 */
export function directionArrow(objective: DiscoveryObjective): string {
  return objective.direction === MINIMIZE ? '↓' : '↑';
}
