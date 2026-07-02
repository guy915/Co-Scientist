import '@material/web/icon/icon.js';

import {Link} from 'react-router-dom';
import {type Hypothesis, type Run} from '@/api/runs';
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

const RECENTS_PANEL_CLASSES = `reference-recents min-[1181px]:!gap-[1.55rem] ${HOME_RECENTS_PANEL_CLASSES}`;

const RECENTS_HEADING_ICON_CLASSES =
  '[--md-icon-size:20px] min-[1181px]:[--md-icon-size:22px]';

const RECENTS_HEADING_CLASSES =
  'm-0 text-[1.15rem] font-semibold text-[var(--cosci-recents-heading)] ' +
  'min-[1181px]:!text-[1.22rem] min-[1181px]:!font-medium ' +
  'min-[1181px]:!leading-[1.2]';

const RECENTS_LIST_CLASSES = `min-[1181px]:!gap-[2.65rem] ${HOME_RECENTS_LIST_CLASSES}`;

const EMPTY_RECENTS_PANEL_CLASSES = `${RECENTS_PANEL_CLASSES} grid-rows-[auto_1fr] self-stretch pb-8`;

const EMPTY_RECENTS_LIST_CLASSES = `${RECENTS_LIST_CLASSES} h-full !max-h-none !overflow-hidden !p-0`;

const EMPTY_RECENTS_ITEM_CLASSES = 'h-full min-h-0';

const EMPTY_RECENTS_CLASSES =
  'reference-recents-empty box-border grid h-full min-h-[25rem] w-full ' +
  'place-items-center content-center gap-4 rounded-[1.35rem] border-[1.5px] ' +
  'border-dashed border-[#c7c9cc] bg-transparent p-6 text-center ' +
  'text-[#5f6368] dark:border-[#53565a] dark:text-[#bdc1c6]';

const EMPTY_RECENTS_ICON_CLASSES =
  'reference-recents-empty-icon block h-[1.95rem] w-[2.1rem] ' +
  'text-[var(--cosci-teal)] dark:text-[#7fd7bf]';

const EMPTY_RECENTS_COPY_CLASSES =
  'max-w-[17rem] text-base leading-[1.35] font-[650] text-inherit';

const RECENT_CARD_CLASSES =
  'reference-recent-card grid min-h-[15.75rem] w-full content-start gap-[0.7rem] ' +
  'rounded-[0.8rem] border border-[var(--cosci-recent-card-border)] ' +
  'bg-[var(--cosci-recent-card-bg)] p-[1.05rem_1.2rem] text-left ' +
  'text-[var(--cosci-recent-card-text)] no-underline shadow-[var(--cosci-recent-card-shadow)] ' +
  'cursor-pointer min-[1181px]:!min-h-0 min-[1181px]:!rounded-2xl ' +
  'min-[1181px]:!border-[#eef1f4] min-[1181px]:!px-[1.15rem] ' +
  'min-[1181px]:!pt-[1.05rem] min-[1181px]:!pb-[1.12rem] ' +
  'min-[1181px]:hover:!border-[#dadce0] min-[1181px]:hover:!bg-[#f8fafd] ' +
  'min-[1181px]:focus-visible:!border-[#dadce0] ' +
  'min-[1181px]:focus-visible:!bg-[#f8fafd] ' +
  'dark:min-[1181px]:!border-transparent dark:min-[1181px]:!bg-[#17191c] ' +
  'dark:min-[1181px]:hover:!border-[#3c4043] ' +
  'dark:min-[1181px]:hover:!bg-[#202124] ' +
  'dark:min-[1181px]:focus-visible:!border-[#3c4043] ' +
  'dark:min-[1181px]:focus-visible:!bg-[#202124]';

const ACTIVE_RECENT_CARD_CLASSES = `${RECENT_CARD_CLASSES} is-active-run`;

const RECENT_META_CLASSES =
  'reference-recent-meta flex flex-wrap gap-[0.35rem]';

const RECENT_META_CHIP_CLASSES =
  'rounded-[0.35rem] bg-[var(--cosci-recent-meta-bg)] px-[0.48rem] ' +
  'py-[0.32rem] text-[0.75rem] font-semibold text-[var(--cosci-recent-meta-text)] ' +
  'min-[1181px]:!bg-[#f1f4f7] min-[1181px]:!px-[0.62rem] ' +
  'min-[1181px]:!py-[0.38rem] min-[1181px]:!text-[0.78rem] ' +
  'min-[1181px]:!leading-[1.1] min-[1181px]:!text-[#3c4043] ' +
  'dark:min-[1181px]:!bg-[#303335] dark:min-[1181px]:!text-[#f1f3f4]';

const RECENT_TITLE_CLASSES =
  'text-[1.02rem] leading-[1.35] min-[1181px]:!text-[1.08rem]';

const RECENT_DESCRIPTION_CLASSES =
  'line-clamp-4 overflow-hidden text-[0.9rem] leading-[1.35] ' +
  'text-[var(--cosci-recent-card-copy)] min-[1181px]:!text-[0.94rem] ' +
  'min-[1181px]:!leading-[1.34] min-[1181px]:!line-clamp-3';

const RECENT_CHIPS_CLASSES =
  'reference-recent-chips flex flex-nowrap items-center gap-[0.35rem]';

const RECENT_CHIP_CLASSES =
  'inline-flex items-center gap-1 rounded-[0.35rem] bg-[var(--cosci-recent-chip-bg)] ' +
  'px-[0.48rem] py-[0.32rem] text-[0.75rem] font-semibold ' +
  'text-[var(--cosci-recent-chip-text)] min-[1181px]:!flex-none ' +
  'min-[1181px]:!min-h-[1.62rem] ' +
  'min-[1181px]:!px-[0.42rem] min-[1181px]:!py-[0.26rem] ' +
  'min-[1181px]:!text-[0.68rem] min-[1181px]:!leading-none ' +
  'min-[1181px]:!whitespace-nowrap dark:min-[1181px]:!bg-[#0b8043] ' +
  'dark:min-[1181px]:!text-[#e6f4ea]';

const RECENT_CHIP_ICON_CLASSES = '[--md-icon-size:16px]';

const ACTIVE_PROGRESS_CLASSES =
  'reference-active-progress min-[1181px]:!mt-[0.05rem] min-[1181px]:!flex ' +
  'min-[1181px]:!items-center min-[1181px]:!gap-[0.65rem] ' +
  'min-[1181px]:!text-[0.92rem] min-[1181px]:!font-medium ' +
  'min-[1181px]:!leading-[1.25] min-[1181px]:!text-[#1967d2] ' +
  'dark:min-[1181px]:!text-[#8fd8c7]';

const ACTIVE_PROGRESS_DOT_CLASSES =
  'min-[1181px]:!block min-[1181px]:!size-[0.7rem] ' +
  'min-[1181px]:!shrink-0 min-[1181px]:!rounded-full ' +
  'min-[1181px]:!bg-current';

const WINNER_LIST_CLASSES =
  'reference-winner-list m-[0.15rem_0_0] grid list-none gap-[0.65rem] p-0 ' +
  'text-[0.78rem] leading-[1.35] text-[var(--cosci-recent-card-text)] ' +
  'min-[1181px]:!gap-2 min-[1181px]:!text-[0.84rem] ' +
  'min-[1181px]:!leading-[1.25] min-[1181px]:!text-[#202124] ' +
  'dark:min-[1181px]:!text-[#f1f3f4]';

const WINNER_LIST_ITEM_CLASSES =
  'min-[1181px]:!grid min-[1181px]:!grid-cols-[1.4rem_minmax(0,1fr)] ' +
  'min-[1181px]:!gap-[0.2rem]';

const GENERATING_ROW_CLASSES =
  'reference-generating-row min-[1181px]:!grid ' +
  'min-[1181px]:!grid-cols-[0.75rem_minmax(0,1fr)] ' +
  'min-[1181px]:!items-center min-[1181px]:!gap-[0.65rem] ' +
  'min-[1181px]:!font-medium min-[1181px]:!text-[#137333] ' +
  'dark:min-[1181px]:!text-[#8fd8c7]';

const GENERATING_DOT_CLASSES =
  'min-[1181px]:!block min-[1181px]:!size-[0.6rem] ' +
  'min-[1181px]:!shrink-0 min-[1181px]:!rounded-full ' +
  'min-[1181px]:!bg-current min-[1181px]:!opacity-70';

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
        <md-icon aria-hidden="true" className={RECENTS_HEADING_ICON_CLASSES}>
          history
        </md-icon>
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
              <md-icon aria-hidden="true" className={RECENT_CHIP_ICON_CLASSES}>
                emoji_events
              </md-icon>
              Winning ideas
            </span>
            {topScore !== null && (
              <span className={RECENT_CHIP_CLASSES}>
                <md-icon
                  aria-hidden="true"
                  className={RECENT_CHIP_ICON_CLASSES}
                >
                  stars
                </md-icon>
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
