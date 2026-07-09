import {isActiveStatus, type Run} from '@/api/runs';
import {isLiverFibrosisGoal} from '@/lib/demo_domains';
import {formatDurationPhrase} from '@/lib/duration';
import {conciseTitle} from '@/lib/text';

// Formats a run's creation date for the meta chip, e.g. "July 8, 2026".
// Timestamps on Run are Unix seconds, hence the *1000 to build a Date.
const HOME_RUN_DATE_FMT = new Intl.DateTimeFormat(undefined, {
  month: 'long',
  day: 'numeric',
  year: 'numeric',
});

/**
 * Formats a run's creation date for the recents-card meta chip, e.g.
 * "July 8, 2026".
 *
 * @param timestamp The run's creation time in Unix seconds.
 * @returns The localized long-form date string.
 */
export function formatHomeRunDate(timestamp: number): string {
  return HOME_RUN_DATE_FMT.format(new Date(timestamp * 1000));
}

// Wall-clock duration phrase when the run has a valid end timestamp after
// its start, else null.
function completedDurationLabel(run: Run): string | null {
  const endTime = run.completed_at ?? run.updated_at;
  if (!endTime || endTime <= run.created_at) return null;
  return formatDurationPhrase(endTime - run.created_at);
}

// Total wall-clock duration for a finished (or presumed-finished) run. Falls
// back to a flat 60s phrase for completed runs missing a proper end
// timestamp, "In progress" for active runs, and the raw status otherwise.
function formatHomeRunDuration(run: Run): string {
  const completed = completedDurationLabel(run);
  if (completed !== null) return completed;
  if (run.status === 'completed') return formatDurationPhrase(60);
  if (isActiveStatus(run.status)) return 'In progress';
  return formatHomeRunStatus(run);
}

// Elapsed time since an active run was created, floored at zero to guard
// against clock skew between client and server timestamps.
function formatHomeRunElapsed(run: Run): string {
  const elapsedSeconds = Math.max(
    0,
    (run.updated_at || Date.now() / 1000) - run.created_at,
  );
  if (elapsedSeconds < 60) return '< 1 minute';
  return formatDurationPhrase(elapsedSeconds);
}

/**
 * Builds the second meta chip on a recent-run card: total time once
 * completed, live elapsed time while active, or the raw status label
 * otherwise.
 *
 * @param run The run to describe.
 * @returns The chip text.
 */
export function formatHomeRunTimeChip(run: Run): string {
  if (run.status === 'completed') {
    return `Total time: ${formatHomeRunDuration(run)}`;
  }
  if (isActiveStatus(run.status)) {
    return `Time elapsed: ${formatHomeRunElapsed(run)}`;
  }
  return `Status: ${formatHomeRunStatus(run)}`;
}

function formatHomeRunStatus(run: Run): string {
  return run.status.charAt(0).toUpperCase() + run.status.slice(1);
}

/**
 * Looks up a completed run's top score, distinguishing "no entry yet" (score
 * still loading) from "known to be null" via hasOwnProperty rather than a
 * plain index lookup, since both cases would otherwise read as undefined.
 *
 * @param run The run whose score to resolve.
 * @param scoresByRunId Top Elo score per run id.
 * @returns The top score, or null if unknown/not completed.
 */
export function homeRunScore(
  run: Run,
  scoresByRunId: Record<string, number | null>,
): number | null {
  if (run.status !== 'completed') return null;
  return Object.prototype.hasOwnProperty.call(scoresByRunId, run.id)
    ? scoresByRunId[run.id]
    : null;
}

// Elapsed minutes since an active run was created, floored at zero to guard
// against client/server clock skew.
function homeRunElapsedMinutes(run: Run): number {
  return Math.max(
    0,
    ((run.updated_at || Date.now() / 1000) - run.created_at) / 60,
  );
}

/**
 * Derives the 1-based active step (1-4) for a live run. The run summary carries
 * no fine-grained stage, so this mirrors the existing progress heuristic:
 * `queued` sits on Exploring, `synthesizing` on the final Tournament step, and
 * `running` advances Generating -> Reviewing -> Tournament by elapsed
 * minutes so the flow visibly moves without a backend stage signal.
 *
 * @param run The active run.
 * @returns The active step index in the range 1-4.
 */
export function homeRunStepIndex(run: Run): number {
  if (run.status === 'queued') return 1;
  if (run.status === 'synthesizing') return 4;
  const elapsedMinutes = homeRunElapsedMinutes(run);
  if (elapsedMinutes < 1) return 2;
  if (elapsedMinutes < 2) return 3;
  return 4;
}

// Keyword -> placeholder "winning ideas" title set for a recents card (see
// homeRunIdeaTitles). Checked in order; the first matching rule wins.
const HOME_RUN_IDEA_TITLE_RULES: {
  test: (normalized: string, goal: string) => boolean;
  titles: string[];
}[] = [
  {
    test: normalized =>
      normalized.includes('ferroptosis') || normalized.includes('pancreatic'),
    titles: [
      'Mitochondrial feedback rescue hypothesis',
      'Lipid peroxide buffering threshold hypothesis',
      'Iron-trafficking checkpoint hypothesis',
    ],
  },
  {
    test: (_normalized, goal) => isLiverFibrosisGoal(goal),
    titles: [
      'Epigenetic stromal reversal hypothesis',
      'Fibrotic memory erasure hypothesis',
      'Macrophage remodeling checkpoint hypothesis',
    ],
  },
  {
    test: normalized =>
      normalized.includes('m.tuberculosis') ||
      normalized.includes('tuberculosis'),
    titles: [
      'Metabolic refuge disruption hypothesis',
      'Biofilm redox-state vulnerability hypothesis',
      'Quorum-linked susceptibility restoration hypothesis',
    ],
  },
  {
    test: normalized =>
      normalized.includes('synaptic') || normalized.includes('pruning'),
    titles: [
      'Microglial timing-window pruning hypothesis',
      'Complement-gated flexibility hypothesis',
      'Activity-dependent dendritic retention hypothesis',
    ],
  },
];

/**
 * Maps a run's goal text to a fixed, plausible-looking set of three "winning
 * idea" titles by keyword-matching known demo topics; any unmatched goal
 * falls back to its own concise title plus two generic hypothesis labels.
 * This is decorative placeholder content - the run summary has no real
 * per-hypothesis titles to show here.
 *
 * @param goal The run's research goal text.
 * @returns Three placeholder "winning idea" titles.
 */
export function homeRunIdeaTitles(goal: string): string[] {
  const normalized = goal.toLowerCase();
  const rule = HOME_RUN_IDEA_TITLE_RULES.find(({test}) =>
    test(normalized, goal),
  );
  if (rule) return rule.titles;
  return [
    conciseTitle(goal),
    'Mechanistic differentiation hypothesis',
    'Evidence-guided intervention hypothesis',
  ];
}
