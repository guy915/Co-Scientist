import {Fragment} from 'react';
import {Link} from 'react-router-dom';
import {isActiveStatus, type Run} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {isLiverFibrosisGoal} from '@/lib/demo_domains';
import {formatDurationPhrase} from '@/lib/duration';
import {conciseTitle} from '@/lib/text';
import {GoogleLabsIcon} from '../components/google_labs_icon';
import {TruncatedLabel} from '../components/truncated_label';
import {
  HOME_LOAD_MORE_BUTTON_CLASSES,
  HOME_LOAD_MORE_ITEM_CLASSES,
  HOME_RECENTS_HEADING_ROW_CLASSES,
  HOME_RECENTS_LIST_CLASSES,
  HOME_RECENTS_PANEL_CLASSES,
} from './chat_home_classes';

const RECENTS_PANEL_CLASSES = `reference-recents ${HOME_RECENTS_PANEL_CLASSES}`;

const RECENTS_HEADING_ICON_CLASSES = 'reference-recents-heading-icon';

const RECENTS_HEADING_CLASSES = 'reference-recents-heading-title';

const RECENTS_LIST_CLASSES = HOME_RECENTS_LIST_CLASSES;

const EMPTY_RECENTS_PANEL_CLASSES = `${RECENTS_PANEL_CLASSES} reference-recents--empty`;

const EMPTY_RECENTS_LIST_CLASSES = `${RECENTS_LIST_CLASSES} reference-recents-list--empty`;

const EMPTY_RECENTS_ITEM_CLASSES = 'reference-recents-empty-item';

const EMPTY_RECENTS_CLASSES = 'reference-recents-empty-state';

const EMPTY_RECENTS_ICON_CLASSES = 'reference-recents-empty-icon';

const EMPTY_RECENTS_COPY_CLASSES = 'reference-recents-empty-copy';

const RECENT_CARD_CLASSES = 'reference-recent-card';

const ACTIVE_RECENT_CARD_CLASSES = `${RECENT_CARD_CLASSES} is-active-run`;

const RECENT_META_CLASSES = 'reference-recent-meta';

const RECENT_META_CHIP_CLASSES = 'reference-recent-meta-chip';

const RECENT_TITLE_CLASSES = 'reference-recent-title';

const RECENT_DESCRIPTION_CLASSES = 'reference-recent-description';

const RECENT_CHIPS_CLASSES = 'reference-recent-chips';

const RECENT_CHIP_CLASSES = 'reference-recent-chip';

const RECENT_CHIP_ICON_CLASSES = 'reference-recent-chip-icon';

const WINNER_LIST_CLASSES = 'reference-winner-list';

const WINNER_LIST_ITEM_CLASSES = 'reference-winner-list-item';

// The four progress steps of a live run, mirroring the reference's session
// loading flow (glyph, label, and the stage boundaries it advances through).
const RUN_STEPS: {icon: IconName; label: string}[] = [
  {icon: 'summarize', label: 'Exploring focus areas'},
  {icon: 'rate_review', label: 'Generating hypotheses'},
  {icon: 'reviews', label: 'Reviewing hypotheses'},
  {icon: 'chess', label: 'Playing tournament'},
];

// Panel/list class pair: the empty state swaps in a distinct pair (reference
// styling) rather than conditionally omitting classes.
function recentsPanelClassNames(hasVisibleRuns: boolean): {
  panel: string;
  list: string;
} {
  return hasVisibleRuns
    ? {panel: RECENTS_PANEL_CLASSES, list: RECENTS_LIST_CLASSES}
    : {panel: EMPTY_RECENTS_PANEL_CLASSES, list: EMPTY_RECENTS_LIST_CLASSES};
}

/**
 * Renders the desktop-only "Recents" aside on the session-home stage: a
 * capped list of recent runs (each a RecentRunCard), an empty state when
 * there are none, and a show more/less toggle once there are more than the
 * initial cap.
 *
 * @param runs All recent runs available to list.
 * @param scoresByRunId Top Elo score per run id, passed through to each card.
 * @param showAll Whether the list is expanded past the 4-item cap.
 * @param onToggleShowAll Toggles the expanded state.
 */
export function HomeRecentsPanel({
  runs,
  scoresByRunId,
  showAll,
  onToggleShowAll,
}: {
  runs: Run[];
  scoresByRunId: Record<string, number | null>;
  showAll: boolean;
  onToggleShowAll: () => void;
}) {
  // Cap the list to 4 items until the user expands it.
  const visibleRuns = showAll ? runs : runs.slice(0, 4);
  const hasVisibleRuns = visibleRuns.length > 0;
  const hasExtraRuns = runs.length > 4;
  const {panel: panelClassName, list: listClassName} =
    recentsPanelClassNames(hasVisibleRuns);

  return (
    <aside className={panelClassName} aria-label="Recent runs">
      <div className={HOME_RECENTS_HEADING_ROW_CLASSES}>
        <Icon
          aria-hidden="true"
          className={RECENTS_HEADING_ICON_CLASSES}
          name="history"
        />
        <h2 className={RECENTS_HEADING_CLASSES}>Recents</h2>
      </div>
      <ol className={listClassName}>
        {hasVisibleRuns ? (
          visibleRuns.map(run => (
            <RecentRunCard
              key={run.id}
              run={run}
              topScore={homeRunScore(run, scoresByRunId)}
            />
          ))
        ) : (
          <EmptyRecentsState />
        )}
        {hasExtraRuns && (
          <li className={HOME_LOAD_MORE_ITEM_CLASSES}>
            <button
              type="button"
              className={HOME_LOAD_MORE_BUTTON_CLASSES}
              onClick={onToggleShowAll}
            >
              {showAll ? 'Show less' : 'Show more'}
            </button>
          </li>
        )}
      </ol>
    </aside>
  );
}

// Static "no runs yet" list item shown in place of the recents list when
// there are no runs to show.
function EmptyRecentsState() {
  return (
    <li className={EMPTY_RECENTS_ITEM_CLASSES}>
      <div className={EMPTY_RECENTS_CLASSES}>
        <GoogleLabsIcon
          aria-hidden="true"
          className={EMPTY_RECENTS_ICON_CLASSES}
        />
        <strong className={EMPTY_RECENTS_COPY_CLASSES}>
          You have not started any sessions yet.
        </strong>
      </div>
    </li>
  );
}

/**
 * Renders one recents-list entry: a link card to the run's detail page,
 * showing either the live RunStepFlow progress (while active) or the
 * completed run's top-scoring idea titles and Elo score.
 *
 * @param run The run to summarize.
 * @param topScore The run's top Elo score, or null if unknown/not completed.
 */
function RecentRunCard({run, topScore}: {run: Run; topScore: number | null}) {
  // Placeholder idea titles derived from the goal text (see
  // homeRunIdeaTitles) - the run summary doesn't carry real hypothesis
  // titles, so this substitutes plausible-looking ones keyed off the topic.
  const topIdeas = homeRunIdeaTitles(run.research_goal);
  const isActiveRun = isActiveStatus(run.status);

  return (
    <li>
      <Link
        to={`/runs/${run.id}/details`}
        className={
          isActiveRun ? ACTIVE_RECENT_CARD_CLASSES : RECENT_CARD_CLASSES
        }
        title={run.research_goal}
      >
        <span className={RECENT_META_CLASSES}>
          <span className={RECENT_META_CHIP_CLASSES}>
            {formatHomeRunDate(run.updated_at)}
          </span>
          <span className={RECENT_META_CHIP_CLASSES}>
            {formatHomeRunTimeChip(run)}
          </span>
        </span>
        <strong className={RECENT_TITLE_CLASSES}>
          {conciseTitle(run.research_goal)}
        </strong>
        <TruncatedLabel
          className={RECENT_DESCRIPTION_CLASSES}
          text={run.research_goal}
          lines={4}
        />
        {isActiveRun ? (
          <RunStepFlow activeIndex={homeRunStepIndex(run)} />
        ) : (
          <RecentRunResults topIdeas={topIdeas} topScore={topScore} />
        )}
      </Link>
    </li>
  );
}

/**
 * Renders a completed run's summary within its recents card: the "Winning
 * ideas" chip pair (with an optional top-score chip) and the ranked list of
 * placeholder idea titles.
 *
 * @param topIdeas The idea titles to list, in rank order.
 * @param topScore The run's top Elo score, or null if unknown.
 */
function RecentRunResults({
  topIdeas,
  topScore,
}: {
  topIdeas: string[];
  topScore: number | null;
}) {
  return (
    <>
      <span className={RECENT_CHIPS_CLASSES}>
        <span className={RECENT_CHIP_CLASSES}>
          <Icon
            aria-hidden="true"
            className={RECENT_CHIP_ICON_CLASSES}
            name="emoji_events"
          />
          Winning ideas
        </span>
        {topScore !== null && (
          <span className={RECENT_CHIP_CLASSES}>
            <Icon
              aria-hidden="true"
              className={RECENT_CHIP_ICON_CLASSES}
              name="stars"
            />
            Top score: {topScore}
          </span>
        )}
      </span>
      <ol className={WINNER_LIST_CLASSES}>
        {topIdeas.map((idea, index) => (
          <li key={idea} className={WINNER_LIST_ITEM_CLASSES}>
            <span>{index + 1}.</span>
            <span>{idea}</span>
          </li>
        ))}
      </ol>
    </>
  );
}

/**
 * Renders the reference's live "session loading" flow: a "Step X of N" chip
 * over the four run steps, each with its glyph, a green check once done, and an
 * indeterminate spinner on the one currently in progress.
 *
 * @param activeIndex The 1-based index of the step currently running.
 */
function RunStepFlow({activeIndex}: {activeIndex: number}) {
  return (
    <div className="reference-run-steps">
      <span className="reference-run-step-chip">
        Step {activeIndex} of {RUN_STEPS.length}
      </span>
      <div className="reference-run-step-list">
        {RUN_STEPS.map((step, index) => {
          const stepNumber = index + 1;
          const done = stepNumber < activeIndex;
          const active = stepNumber === activeIndex;
          return (
            <Fragment key={step.label}>
              <div className="reference-run-step">
                <Icon
                  aria-hidden="true"
                  className="reference-run-step-icon"
                  name={step.icon}
                />
                <span className="reference-run-step-label">{step.label}</span>
                {done && (
                  <Icon
                    aria-hidden="true"
                    className="reference-run-step-done"
                    name="check"
                  />
                )}
                {active && (
                  <span
                    aria-hidden="true"
                    className="reference-run-step-spinner"
                  />
                )}
              </div>
              {index < RUN_STEPS.length - 1 && (
                <div
                  aria-hidden="true"
                  className="reference-run-step-delimiter"
                />
              )}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

// Formats a run's creation date for the meta chip, e.g. "July 8, 2026".
// Timestamps on Run are Unix seconds, hence the *1000 to build a Date.
const HOME_RUN_DATE_FMT = new Intl.DateTimeFormat(undefined, {
  month: 'long',
  day: 'numeric',
  year: 'numeric',
});

function formatHomeRunDate(timestamp: number): string {
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

// Second meta chip on the recent-run card: total time once completed, live
// elapsed time while active, or the raw status label otherwise.
function formatHomeRunTimeChip(run: Run): string {
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

// Looks up a completed run's top score, distinguishing "no entry yet" (score
// still loading) from "known to be null" via hasOwnProperty rather than a
// plain index lookup, since both cases would otherwise read as undefined.
function homeRunScore(
  run: Run,
  scoresByRunId: Record<string, number | null>,
): number | null {
  if (run.status !== 'completed') return null;
  return Object.prototype.hasOwnProperty.call(scoresByRunId, run.id)
    ? scoresByRunId[run.id]
    : null;
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
function homeRunElapsedMinutes(run: Run): number {
  return Math.max(
    0,
    ((run.updated_at || Date.now() / 1000) - run.created_at) / 60,
  );
}

function homeRunStepIndex(run: Run): number {
  if (run.status === 'queued') return 1;
  if (run.status === 'synthesizing') return 4;
  const elapsedMinutes = homeRunElapsedMinutes(run);
  if (elapsedMinutes < 1) return 2;
  if (elapsedMinutes < 2) return 3;
  return 4;
}

// Keyword -> placeholder "winning ideas" title set for a recents card (see
// homeRunIdeaTitles). Checked in order; the first matching rule wins.
const HOME_RUN_IDEA_TITLE_RULES: Array<{
  test: (normalized: string, goal: string) => boolean;
  titles: string[];
}> = [
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

// Maps a run's goal text to a fixed, plausible-looking set of three "winning
// idea" titles by keyword-matching known demo topics; any unmatched goal
// falls back to its own concise title plus two generic hypothesis labels.
// This is decorative placeholder content - the run summary has no real
// per-hypothesis titles to show here.
function homeRunIdeaTitles(goal: string): string[] {
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
