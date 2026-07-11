import {Link} from 'react-router-dom';
import {isActiveStatus, type Run} from '@/api/runs';
import {Icon} from '@/components/icon';
import {firstSentenceClause} from '@/lib/text';
import {GoogleLabsIcon} from '../components/google_labs_icon';
import {TruncatedLabel} from '../components/truncated_label';
import {
  HOME_LOAD_MORE_BUTTON_CLASSES,
  HOME_LOAD_MORE_ITEM_CLASSES,
  HOME_RECENTS_HEADING_ROW_CLASSES,
  HOME_RECENTS_LIST_CLASSES,
  HOME_RECENTS_PANEL_CLASSES,
} from './chat_home_classes';
import {
  formatHomeRunDate,
  formatHomeRunTimeChip,
  homeRunScore,
  homeRunStepIndex,
} from './home_recents_data';
import {RunStepFlow} from './home_recents_run_steps';

const RECENTS_PANEL_CLASSES = `reference-recents ${HOME_RECENTS_PANEL_CLASSES}`;

const RECENTS_HEADING_ICON_CLASSES = 'reference-recents-heading-icon';

const RECENTS_HEADING_CLASSES = 'reference-recents-heading-title';

const RECENTS_LIST_CLASSES = HOME_RECENTS_LIST_CLASSES;

const EMPTY_RECENTS_PANEL_CLASSES =
  RECENTS_PANEL_CLASSES + ' reference-recents--empty';

const EMPTY_RECENTS_LIST_CLASSES =
  RECENTS_LIST_CLASSES + ' reference-recents-list--empty';

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
      <RecentsHeading />
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
          <LoadMoreRunsItem
            showAll={showAll}
            onToggleShowAll={onToggleShowAll}
          />
        )}
      </ol>
    </aside>
  );
}

// The panel's "Recents" heading row: history glyph plus title.
function RecentsHeading() {
  return (
    <div className={HOME_RECENTS_HEADING_ROW_CLASSES}>
      <Icon
        aria-hidden="true"
        className={RECENTS_HEADING_ICON_CLASSES}
        name="history"
      />
      <h2 className={RECENTS_HEADING_CLASSES}>Recents</h2>
    </div>
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

// Trailing list item toggling between the capped and full recents list.
function LoadMoreRunsItem({
  showAll,
  onToggleShowAll,
}: {
  showAll: boolean;
  onToggleShowAll: () => void;
}) {
  return (
    <li className={HOME_LOAD_MORE_ITEM_CLASSES}>
      <button
        type="button"
        className={HOME_LOAD_MORE_BUTTON_CLASSES}
        onClick={onToggleShowAll}
      >
        {showAll ? 'Show less' : 'Show more'}
      </button>
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
  // The run's real top hypotheses by Elo, served on the run-list payload
  // (`top_hypotheses`). Empty for a run that produced none (e.g. failed).
  const topIdeas = run.top_hypotheses ?? [];
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
        <TruncatedLabel
          className={RECENT_TITLE_CLASSES}
          text={firstSentenceClause(run.research_goal) || 'Untitled session'}
          lines={2}
        />

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
 * the run's real top hypothesis titles. The list is omitted when the run
 * produced no hypotheses.
 *
 * @param topIdeas The run's top hypothesis titles, in rank order.
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
      {topIdeas.length > 0 && (
        <ol className={WINNER_LIST_CLASSES}>
          {topIdeas.map((idea, index) => (
            <li key={idea} className={WINNER_LIST_ITEM_CLASSES}>
              <span>{index + 1}.</span>
              <span>{idea}</span>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
