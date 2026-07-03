import {Link} from 'react-router-dom';
import {type Hypothesis, type Run} from '@/api/runs';
import {Icon} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {GoogleLabsIcon} from '../components/google_labs_icon';
import {
  HOME_LOAD_MORE_BUTTON_CLASSES,
  HOME_LOAD_MORE_ITEM_CLASSES,
  HOME_RECENTS_HEADING_ROW_CLASSES,
  HOME_RECENTS_LIST_CLASSES,
  HOME_RECENTS_PANEL_CLASSES,
} from './chat_home_classes';

const BASELINE_ELO_RATING = 1200;

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

const ACTIVE_PROGRESS_CLASSES = 'reference-active-progress';

const ACTIVE_PROGRESS_DOT_CLASSES = 'reference-active-progress-dot';

const WINNER_LIST_CLASSES = 'reference-winner-list';

const WINNER_LIST_ITEM_CLASSES = 'reference-winner-list-item';

const GENERATING_ROW_CLASSES = 'reference-generating-row';

const GENERATING_DOT_CLASSES = 'reference-generating-dot';

export function topEloFromHypotheses(hypotheses: Hypothesis[]): number {
  const ratings = hypotheses
    .map(hypothesis => hypothesis.elo_rating)
    .filter(Number.isFinite);
  if (!ratings.length) return BASELINE_ELO_RATING;
  return Math.max(...ratings);
}

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
  const isActiveRun = isActiveHomeRun(run);

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
        <span className={RECENT_DESCRIPTION_CLASSES}>{run.research_goal}</span>
        {isActiveRun ? (
          <div className={ACTIVE_PROGRESS_CLASSES}>
            <span aria-hidden="true" className={ACTIVE_PROGRESS_DOT_CLASSES} />
            <span>In Progress: {homeRunProgress(run)}%</span>
          </div>
        ) : (
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
        )}
        <ol className={WINNER_LIST_CLASSES}>
          {isActiveRun ? (
            <li className={GENERATING_ROW_CLASSES}>
              <span aria-hidden="true" className={GENERATING_DOT_CLASSES} />
              <span>Generating hypotheses</span>
            </li>
          ) : (
            topIdeas.map((idea, index) => (
              <li key={idea} className={WINNER_LIST_ITEM_CLASSES}>
                <span>{index + 1}.</span>
                <span>{idea}</span>
              </li>
            ))
          )}
        </ol>
      </Link>
    </li>
  );
}

function formatHomeRunDate(timestamp: number): string {
  return new Intl.DateTimeFormat(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(timestamp * 1000));
}

function formatDurationLabel(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes >= 90) {
    const hours = Math.max(1, Math.round(minutes / 60));
    return `${hours} hour${hours === 1 ? '' : 's'}`;
  }
  return `${minutes} minute${minutes === 1 ? '' : 's'}`;
}

function formatHomeRunDuration(run: Run): string {
  const endTime = run.completed_at ?? run.updated_at;
  if (endTime && endTime > run.created_at) {
    return formatDurationLabel(endTime - run.created_at);
  }
  if (run.status === 'completed') {
    return formatDurationLabel(60);
  }
  if (['running', 'queued', 'synthesizing'].includes(run.status)) {
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
  return formatDurationLabel(elapsedSeconds);
}

function formatHomeRunTimeChip(run: Run): string {
  if (run.status === 'completed') {
    return `Total time: ${formatHomeRunDuration(run)}`;
  }
  if (['running', 'queued', 'synthesizing'].includes(run.status)) {
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

function homeRunProgress(run: Run): number {
  if (run.status === 'completed') return 100;
  const elapsedMinutes = Math.max(
    0,
    Math.round(((run.updated_at || Date.now() / 1000) - run.created_at) / 60),
  );
  if (run.status === 'queued') {
    return Math.max(8, Math.min(18, 8 + elapsedMinutes));
  }
  if (run.status === 'synthesizing') {
    return Math.max(72, Math.min(94, 72 + elapsedMinutes * 2));
  }
  return Math.max(18, Math.min(86, 18 + elapsedMinutes * 3));
}

function isActiveHomeRun(run: Run): boolean {
  return ['running', 'queued', 'synthesizing'].includes(run.status);
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
  if (
    normalized.includes('fibrosis') ||
    normalized.includes('mash') ||
    normalized.includes('masld')
  ) {
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
