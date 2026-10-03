import {Link} from 'react-router-dom';
import {
  isActiveStatus,
  isCompletedStatus,
  type ChatSummary,
  type Run,
} from '@/api/runs';
import {Icon} from '@/components/icon';
import {firstSentenceClause} from '@/lib/text';
import {useNowTick} from '@/workbench/hooks/timers';
import {GoogleLabsIcon} from '../components/google_labs_icon';
import {TruncatedLabel} from '../components/truncated_label';
import {preferredSessionSide} from '../layout_session_memory';
import {formatHomeRunDate, formatHomeRunTimeChip} from './home_recents_data';
import {RunStepFlow} from './home_recents_run_steps';

interface HomeRecentsPanelProps {
  runs: Run[];
  showAll: boolean;
  onToggleShowAll: () => void;
  chats?: readonly ChatSummary[];
}

export function HomeRecentsPanel({
  runs,
  showAll,
  onToggleShowAll,
  chats = [],
}: HomeRecentsPanelProps) {
  const visibleRuns = showAll ? runs : runs.slice(0, 4);
  const empty = visibleRuns.length === 0;
  return (
    <aside
      className={`reference-recents reference-recents-panel${empty ? ' reference-recents--empty' : ''}`}
      aria-label="Recent runs"
    >
      <div className="reference-recents-heading">
        <Icon
          aria-hidden="true"
          className="reference-recents-heading-icon"
          name="history"
        />
        <h2 className="reference-recents-heading-title">Recents</h2>
      </div>
      <ol
        className={`reference-recents-list${empty ? ' reference-recents-list--empty' : ''}`}
      >
        {empty ? (
          <li className="reference-recents-empty-item">
            <div className="reference-recents-empty-state">
              <GoogleLabsIcon
                aria-hidden="true"
                className="reference-recents-empty-icon"
              />
              <strong className="reference-recents-empty-copy">
                You have not started any sessions yet.
              </strong>
            </div>
          </li>
        ) : (
          visibleRuns.map(run => (
            <RecentRunCard key={run.id} run={run} chats={chats} />
          ))
        )}
        {runs.length > 4 && (
          <li className="reference-load-more-item">
            <button
              type="button"
              className="reference-load-more"
              onClick={onToggleShowAll}
            >
              {showAll ? 'Show less' : 'Show more'}
              <Icon
                aria-hidden="true"
                name={showAll ? 'expand_less' : 'expand_more'}
              />
            </button>
          </li>
        )}
      </ol>
    </aside>
  );
}

function RecentCardMeta({run}: {run: Run}) {
  const nowSeconds = useNowTick(1000);
  return (
    <span className="reference-recent-meta">
      <span className="reference-recent-meta-chip">
        {formatHomeRunDate(run.updated_at)}
      </span>
      <span className="reference-recent-meta-chip">
        {formatHomeRunTimeChip(run, nowSeconds)}
      </span>
    </span>
  );
}

function RecentRunCard({
  run,
  chats,
}: {
  run: Run;
  chats: readonly ChatSummary[];
}) {
  // Resolve the remembered Chat/Results side from the current chat list.
  const chat =
    preferredSessionSide(run.id) === 'chat'
      ? chats.find(entry => entry.run_id === run.id)
      : undefined;
  const active = isActiveStatus(run.status);
  return (
    <li>
      <Link
        to={chat ? `/chats/${chat.id}` : `/runs/${run.id}/details`}
        className={`reference-recent-card${active ? ' is-active-run' : ''}`}
        title={run.research_goal}
      >
        <RecentCardMeta run={run} />
        <TruncatedLabel
          className="reference-recent-title"
          text={
            run.title ||
            firstSentenceClause(run.research_goal) ||
            'Untitled session'
          }
          lines={2}
        />
        <TruncatedLabel
          className="reference-recent-description"
          text={run.research_goal}
          lines={3}
        />
        {active ? (
          <RunStepFlow run={run} />
        ) : (
          isCompletedStatus(run.status) && <RecentRunResults run={run} />
        )}
      </Link>
    </li>
  );
}

function RecentRunResults({run}: {run: Run}) {
  const topIdeas = run.top_hypotheses ?? [];
  const topScore = run.top_elo ?? null;
  return (
    <>
      <span className="reference-recent-chips">
        <span className="reference-recent-chip">
          <Icon
            aria-hidden="true"
            className="reference-recent-chip-icon"
            name="emoji_events"
          />
          Winning ideas
        </span>
        {topScore !== null && (
          <span className="reference-recent-chip">
            <Icon
              aria-hidden="true"
              className="reference-recent-chip-icon"
              name="stars"
            />
            Top score: {topScore}
          </span>
        )}
      </span>
      {topIdeas.length > 0 && (
        <ol className="reference-winner-list">
          {topIdeas.map((idea, index) => (
            <li key={idea} className="reference-winner-list-item">
              <span>{index + 1}.</span>
              <TruncatedLabel
                className="reference-winner-list-text"
                text={idea}
                lines={2}
              />
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
