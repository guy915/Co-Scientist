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
  const visibleRuns = showAll ? runs : runs.slice(0, 4);
  const hasVisibleRuns = visibleRuns.length > 0;
  const hasExtraRuns = runs.length > 4;
  const panelClassName = hasVisibleRuns
    ? RECENTS_PANEL_CLASSES
    : EMPTY_RECENTS_PANEL_CLASSES;
  const listClassName = hasVisibleRuns
    ? RECENTS_LIST_CLASSES
    : EMPTY_RECENTS_LIST_CLASSES;

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

function RecentRunCard({run, topScore}: {run: Run; topScore: number | null}) {
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
        )}
      </Link>
    </li>
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

function formatHomeRunDate(timestamp: number): string {
  return new Intl.DateTimeFormat(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(timestamp * 1000));
}

function formatHomeRunDuration(run: Run): string {
  const endTime = run.completed_at ?? run.updated_at;
  if (endTime && endTime > run.created_at) {
    return formatDurationPhrase(endTime - run.created_at);
  }
  if (run.status === 'completed') {
    return formatDurationPhrase(60);
  }
  if (isActiveStatus(run.status)) {
    return 'In progress';
  }
  return formatHomeRunStatus(run);
}

function formatHomeRunElapsed(run: Run): string {
  const elapsedSeconds = Math.max(
    0,
    (run.updated_at || Date.now() / 1000) - run.created_at,
  );
  if (elapsedSeconds < 60) return '< 1 minute';
  return formatDurationPhrase(elapsedSeconds);
}

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
 * `running` advances Generating -> Reviewing -> Tournament by elapsed minutes so
 * the flow visibly moves without a backend stage signal.
 *
 * @param run The active run.
 * @returns The active step index in the range 1-4.
 */
function homeRunStepIndex(run: Run): number {
  if (run.status === 'queued') return 1;
  if (run.status === 'synthesizing') return 4;
  const elapsedMinutes = Math.max(
    0,
    ((run.updated_at || Date.now() / 1000) - run.created_at) / 60,
  );
  if (elapsedMinutes < 1) return 2;
  if (elapsedMinutes < 2) return 3;
  return 4;
}

function homeRunIdeaTitles(goal: string): string[] {
  const normalized = goal.toLowerCase();
  if (normalized.includes('ferroptosis') || normalized.includes('pancreatic')) {
    return [
      'Mitochondrial feedback rescue hypothesis',
      'Lipid peroxide buffering threshold hypothesis',
      'Iron-trafficking checkpoint hypothesis',
    ];
  }
  if (isLiverFibrosisGoal(goal)) {
    return [
      'Epigenetic stromal reversal hypothesis',
      'Fibrotic memory erasure hypothesis',
      'Macrophage remodeling checkpoint hypothesis',
    ];
  }
  if (
    normalized.includes('m.tuberculosis') ||
    normalized.includes('tuberculosis')
  ) {
    return [
      'Metabolic refuge disruption hypothesis',
      'Biofilm redox-state vulnerability hypothesis',
      'Quorum-linked susceptibility restoration hypothesis',
    ];
  }
  if (normalized.includes('synaptic') || normalized.includes('pruning')) {
    return [
      'Microglial timing-window pruning hypothesis',
      'Complement-gated flexibility hypothesis',
      'Activity-dependent dendritic retention hypothesis',
    ];
  }
  return [
    conciseTitle(goal),
    'Mechanistic differentiation hypothesis',
    'Evidence-guided intervention hypothesis',
  ];
}
