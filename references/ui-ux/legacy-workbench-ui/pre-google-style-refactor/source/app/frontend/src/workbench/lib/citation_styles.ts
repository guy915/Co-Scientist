/**
 * Shared visual styles for citation / source states, used by the Evidence tab
 * and the grounded Q&A source chips so the colour language stays consistent.
 */

export interface StateStyle {
  fg: string;
  bg: string;
  label: string;
}

/** The four classifier states shown as Evidence-tab filters. */
export const CITATION_STATES = [
  'verified',
  'partial',
  'unsupported',
  'unavailable',
] as const;

export type CitationState = (typeof CITATION_STATES)[number];

const STATE_STYLES: Record<string, StateStyle> = {
  verified: {
    fg: 'var(--color-th-on-success-container)',
    bg: 'var(--color-th-success-container)',
    label: 'Verified',
  },
  partial: {
    fg: 'var(--color-th-on-warning-container)',
    bg: 'var(--color-th-warning-container)',
    label: 'Partial',
  },
  unsupported: {
    fg: 'var(--color-th-destructive-on-container)',
    bg: 'var(--color-th-destructive-container)',
    label: 'Unsupported',
  },
  unavailable: {
    fg: 'var(--color-th-muted-fg)',
    bg: 'var(--color-th-muted)',
    label: 'Unavailable',
  },
  available: {
    fg: 'var(--color-th-muted-fg)',
    bg: 'var(--color-th-muted)',
    label: 'Source',
  },
};

/**
 * Resolve the style for a citation/source state, falling back to a neutral
 * pill for any unknown state string.
 *
 * @param state The state string (e.g. 'verified', 'available').
 * @returns The foreground/background colours and a display label.
 */
export function citationStateStyle(state: string): StateStyle {
  return (
    STATE_STYLES[state] ?? {
      fg: 'var(--color-th-muted-fg)',
      bg: 'var(--color-th-muted)',
      label: state || 'Source',
    }
  );
}
