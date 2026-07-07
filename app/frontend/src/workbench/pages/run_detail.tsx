import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Link, useNavigate, useParams} from 'react-router-dom';
import {
  type Evidence,
  getEvidence,
  getHypotheses,
  getMatches,
  getReport,
  getReviews,
  getRun,
  type Hypothesis,
  type MatchRow,
  type Report,
  type Review,
  type RunWithSummary,
} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {useDebouncedCallback} from '@/hooks/use_debounced_callback';
import {useRunStream} from '@/hooks/use_run_stream';
import {TruncatedLabel} from '../components/truncated_label';
import {IdeasTab} from '../components/tabs/ideas_tab';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_LIST_CLASSES,
  REPORT_SECTION_CLASSES,
  REPORT_SECTION_LIST_ITEM_CLASSES,
  REPORT_SECTION_LIST_META_CLASSES,
  ReportDocument,
  ReportList,
} from './run_detail_document';
import {LearningView} from './run_detail_learning';

const TABS = ['details', 'learning', 'overview', 'ideas'] as const;
type TabName = (typeof TABS)[number];

const TAB_ICON_NAMES: Record<TabName, IconName> = {
  details: 'assignment',
  learning: 'menu_book',
  overview: 'summarize',
  ideas: 'lightbulb',
};

const TAB_LABELS: Record<TabName, string> = {
  details: 'Goal Details',
  learning: 'Learning',
  overview: 'Research Overview',
  ideas: 'All Ideas',
};

const REPORT_PAGE_CLASSES =
  'cosci-report-page grid h-full min-h-0 grid-rows-[3.75rem_5rem_minmax(0,1fr)] bg-cosci-bg text-cosci-fg max-[720px]:min-w-0 max-[720px]:overflow-hidden';

const REPORT_TITLEBAR_CLASSES =
  'cosci-report-titlebar flex min-w-0 items-center justify-between gap-6 border-b border-cosci-border px-9 max-[720px]:gap-[0.35rem] max-[720px]:px-[0.7rem]';

const REPORT_TITLE_LEFT_CLASSES =
  'cosci-report-title-left flex min-w-0 items-center gap-4 max-[720px]:gap-[0.45rem]';

const REPORT_BACK_CLASSES =
  'cosci-report-back grid h-10 w-10 shrink-0 place-items-center rounded-full text-cosci-muted no-underline hover:bg-cosci-hover';

const REPORT_TITLE_CLASSES =
  'm-0 min-w-0 overflow-hidden text-[1.2rem] leading-[1.25] font-normal tracking-normal max-[720px]:text-[0.9rem]';

const REPORT_TITLE_TEXT_CLASSES =
  'block min-w-0 overflow-hidden whitespace-nowrap';

const REPORT_TABS_CLASSES =
  'reference-report-tabs grid grid-cols-4 border-b border-cosci-border max-[720px]:min-w-0 max-[720px]:overflow-x-hidden';

const REPORT_TAB_BUTTON_BASE_CLASSES =
  'relative grid min-w-0 cursor-pointer content-center justify-items-center gap-[0.35rem] border-0 bg-transparent font-[inherit] text-sm max-[720px]:gap-[0.2rem] max-[720px]:text-[0.68rem]';

const REPORT_TAB_SELECTED_CLASSES =
  "text-cosci-blue after:absolute after:right-[1.1rem] after:bottom-0 after:left-[1.1rem] after:h-[0.18rem] after:rounded-t-full after:bg-cosci-blue-strong after:content-['']";

const REPORT_TAB_ICON_CLASSES = 'text-[1.35rem] max-[720px]:text-[1.12rem]';

const REPORT_TAB_LABEL_CLASSES = 'max-[720px]:text-[0.75rem]';

const REPORT_SCROLL_CLASSES =
  'cosci-report-scroll min-h-0 overflow-auto max-[720px]:overflow-x-hidden';

const REPORT_ALERT_CLASSES =
  'cosci-report-alert mx-8 mt-4 rounded-xl border border-cosci-danger-border bg-cosci-danger-bg px-4 py-3 text-cosci-danger-fg';

const REPORT_TOAST_CLASSES =
  'reference-report-toast fixed right-4 bottom-4 z-50 rounded-xl border border-cosci-danger-border bg-cosci-danger-bg px-4 py-3 text-cosci-danger-fg';

const REPORT_SKELETON_CLASSES =
  'cosci-report-skeleton mx-auto my-9 grid w-[min(100%_-_3rem,58rem)] gap-4 max-[720px]:mt-5 max-[720px]:mb-12 max-[720px]:w-[min(100%_-_1.2rem,100%)] max-[720px]:max-w-none';

const ALL_IDEAS_CLASSES = 'cosci-all-ideas h-full p-0';

const REPORT_LEAD_STAT_CLASSES =
  'cosci-overview-lead-stat mt-1 mb-4 text-cosci-fg';

const HOUR_SECONDS = 3600;
const MINUTE_SECONDS = 60;

const TAB_ALIASES: Record<string, TabName> = {
  specifications: 'details',
  specs: 'details',
  knowledge: 'learning',
  evidence: 'learning',
  summary: 'overview',
  report: 'overview',
  hypotheses: 'ideas',
};

/**
 * Renders the Co-Scientist goal report surface from the reference footage.
 */
export function RunDetail() {
  const {id, tab} = useParams<{id: string; tab?: string}>();
  const navigate = useNavigate();
  const activeTab = normalizeTab(tab);

  const [run, setRun] = useState<RunWithSummary | null>(null);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  // Bumped when "All Ideas" is re-tapped, remounting IdeasTab to reset its
  // mobile master-detail selection back to the list.
  const [ideasViewKey, setIdeasViewKey] = useState(0);
  const [toast, setToast] = useState<{
    type: 'info' | 'error';
    message: string;
  } | null>(null);

  const {events, terminal} = useRunStream(id ?? null, 0);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      const [r, h, e, m, rv, rep] = await Promise.all([
        getRun(id),
        getHypotheses(id),
        getEvidence(id),
        getMatches(id),
        getReviews(id),
        getReport(id),
      ]);
      setRun(r);
      setHypotheses(h);
      setEvidence(e);
      setMatches(m);
      setReviews(rv);
      setReport(rep);
      setLoaded(true);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoaded(true);
    }
  }, [id]);

  // Debounced variant for event-driven refetches: the SSE stream replays the
  // full history on mount and live runs emit rapid bursts, so per-event
  // refetches collapse into one trailing call. The identity is stable, and any
  // pending call is cancelled on unmount.
  const debouncedRefresh = useDebouncedCallback(() => void refresh(), 600);

  // Initial load (and reload when the run id changes) stays immediate.
  useEffect(() => {
    debouncedRefresh.cancel();
    void refresh();
  }, [refresh, debouncedRefresh]);

  // Re-pull on new events so tabs stay in sync, debounced to absorb bursts.
  // The stream delivers events in coalesced batches, so scan the whole newly
  // appended slice for a data event rather than only the batch tail: a batch
  // that ends in a 'status' event still warrants a refetch if it carried a
  // node event earlier. The processed-count ref resets naturally when the
  // hook clears events on a run change (length drops back toward zero).
  const processedEventCount = useRef(0);
  useEffect(() => {
    if (events.length < processedEventCount.current) {
      processedEventCount.current = 0;
    }
    const fresh = events.slice(processedEventCount.current);
    processedEventCount.current = events.length;
    if (fresh.some(event => event.type !== 'status')) debouncedRefresh();
  }, [events, debouncedRefresh]);

  // On stream end, refetch immediately so a pending debounce cannot leave the
  // completed state stale.
  useEffect(() => {
    if (!terminal) return;
    debouncedRefresh.cancel();
    void refresh();
  }, [terminal, refresh, debouncedRefresh]);

  useEffect(() => {
    if (!terminal || !run) return;
    if (run.status === 'failed' || run.status === 'blocked') {
      setToast({
        type: 'error',
        message: `Run ${run.status}${run.error ? `: ${run.error}` : ''}`,
      });
    }
  }, [terminal, run]);

  // Full display title (curated domain override, else the goal). Shared by the
  // shell-header dispatch and the titlebar; each host truncates to its own
  // available width via TruncatedLabel rather than being pre-shortened.
  const title = useMemo(() => {
    if (!run) return 'Goal report';
    return (
      domainTitleOverride(run.research_goal) ??
      run.config.setup?.goal ??
      run.research_goal
    );
  }, [run]);

  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent('cosci-header-title', {detail: title}),
    );
    return () => {
      window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: ''}));
    };
  }, [title]);

  const onTabChange = useCallback(
    (nextTab: TabName) => {
      if (!id) return;
      // Tapping "All Ideas" while already on it resets the mobile master-detail
      // back to the list: the detail view has no back button, so re-tapping the
      // tab (which remounts the ideas view via ideasViewKey) is the way back.
      if (nextTab === 'ideas' && activeTab === 'ideas') {
        setIdeasViewKey(key => key + 1);
      }
      // Always include the tab (details included) so every tab is the same
      // required-param route — switching tabs never remounts RunDetail.
      void navigate(`/runs/${id}/${nextTab}`);
    },
    [id, navigate, activeTab],
  );

  if (!id) return null;

  const activeTabIndex = TABS.indexOf(activeTab);

  return (
    <div className={REPORT_PAGE_CLASSES}>
      <header className={REPORT_TITLEBAR_CLASSES}>
        <div className={REPORT_TITLE_LEFT_CLASSES}>
          <Link to="/" className={REPORT_BACK_CLASSES} aria-label="Back">
            <Icon aria-hidden="true" name="arrow_back" />
          </Link>
          <h1 className={REPORT_TITLE_CLASSES}>
            <TruncatedLabel
              className={REPORT_TITLE_TEXT_CLASSES}
              text={title}
            />
          </h1>
        </div>
      </header>

      <nav className={REPORT_TABS_CLASSES} aria-label="Goal report sections">
        {TABS.map((tabName, index) => (
          <button
            key={tabName}
            type="button"
            className={reportTabButtonClass(index === activeTabIndex)}
            aria-current={index === activeTabIndex ? 'page' : undefined}
            onClick={() => onTabChange(tabName)}
          >
            <Icon
              className={REPORT_TAB_ICON_CLASSES}
              aria-hidden="true"
              name={TAB_ICON_NAMES[tabName]}
            />
            <span className={REPORT_TAB_LABEL_CLASSES}>
              {TAB_LABELS[tabName]}
            </span>
          </button>
        ))}
      </nav>

      {error && (
        <div role="alert" className={REPORT_ALERT_CLASSES}>
          {error}
        </div>
      )}

      {!loaded && !error ? (
        <RunDetailSkeleton />
      ) : (
        <main className={REPORT_SCROLL_CLASSES} key={activeTab}>
          {activeTab === 'details' && <GoalDetailsView run={run} />}
          {activeTab === 'learning' && (
            <LearningView
              goal={run?.config.setup?.goal ?? run?.research_goal ?? ''}
              evidence={evidence}
            />
          )}
          {activeTab === 'overview' && (
            <ResearchOverviewView
              run={run}
              report={report}
              hypotheses={hypotheses}
              matches={matches}
            />
          )}
          {activeTab === 'ideas' && (
            <section className={ALL_IDEAS_CLASSES}>
              <IdeasTab
                key={ideasViewKey}
                hypotheses={hypotheses}
                reviews={reviews}
                matches={matches}
              />
            </section>
          )}
        </main>
      )}

      {toast && <RunToast toast={toast} />}
    </div>
  );
}

function reportTabButtonClass(selected: boolean): string {
  return `${REPORT_TAB_BUTTON_BASE_CLASSES} ${
    selected ? REPORT_TAB_SELECTED_CLASSES : 'text-cosci-muted'
  }`;
}

function GoalDetailsView({run}: {run: RunWithSummary | null}) {
  const setup = run?.config.setup;
  const goal = setup?.goal ?? run?.research_goal ?? 'Loading...';

  return (
    <ReportDocument
      title="Research goal details"
      className="cosci-goal-details"
    >
      <h3 className={REPORT_H3_CLASSES}>{domainTitleOverride(goal) ?? goal}</h3>
      <p>
        <strong>Goal:</strong> {goal}
      </p>
      <ReportList title="Requirements" values={setup?.requirements ?? []} />
      <ReportList title="Attributes" values={setup?.attributes ?? []} />
      <ReportList title="Criteria" values={setup?.criteria ?? []} />
    </ReportDocument>
  );
}

function ResearchOverviewView({
  run,
  report,
  hypotheses,
  matches,
}: {
  run: RunWithSummary | null;
  report: Report | null;
  hypotheses: Hypothesis[];
  matches: MatchRow[];
}) {
  const overview = report?.payload.research_overview;
  const leaderboard = report?.payload.leaderboard ?? [];
  const leadStat = researchOverviewLeadStat({
    run,
    leaderboard,
    hypotheses,
    matches,
  });

  return (
    <ReportDocument title="Research overview">
      {leadStat ? <p className={REPORT_LEAD_STAT_CLASSES}>{leadStat}</p> : null}

      {overview?.overview?.summary ? (
        <p>{overview.overview.summary}</p>
      ) : (
        <p>
          The research overview appears after Co-Scientist finishes the final
          synthesis step.
        </p>
      )}

      {overview?.overview?.research_directions?.length ? (
        <section className={REPORT_SECTION_CLASSES}>
          <h3 className={REPORT_H3_CLASSES}>Research directions</h3>
          {overview.overview.research_directions.map(direction => (
            <div key={direction.title}>
              <h4 className={REPORT_H4_CLASSES}>{direction.title}</h4>
              <p>{direction.importance}</p>
              {direction.suggested_experiments.length ? (
                <ul className={REPORT_LIST_CLASSES}>
                  {direction.suggested_experiments.map(experiment => (
                    <li key={experiment}>{experiment}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ))}
        </section>
      ) : null}

      {overview?.nih_specific_aims?.aims?.length ? (
        <section className={REPORT_SECTION_CLASSES}>
          <h3 className={REPORT_H3_CLASSES}>Specific aims</h3>
          {overview.nih_specific_aims.introduction ? (
            <p>{overview.nih_specific_aims.introduction}</p>
          ) : null}
          {overview.nih_specific_aims.aims.map(aim => (
            <div key={aim.aim}>
              <h4 className={REPORT_H4_CLASSES}>{aim.aim}</h4>
              <p>{aim.rationale}</p>
              <p>{aim.approach}</p>
            </div>
          ))}
          {overview.nih_specific_aims.impact ? (
            <p>{overview.nih_specific_aims.impact}</p>
          ) : null}
        </section>
      ) : null}

      {leaderboard.length ? (
        <section className={REPORT_SECTION_CLASSES}>
          <h3 className={REPORT_H3_CLASSES}>Winning ideas</h3>
          <ol className={REPORT_LIST_CLASSES}>
            {leaderboard.slice(0, 5).map(item => (
              <li className={REPORT_SECTION_LIST_ITEM_CLASSES} key={item.id}>
                <strong>{item.title}</strong>
                <span className={REPORT_SECTION_LIST_META_CLASSES}>
                  Elo rating: {item.elo}
                </span>
              </li>
            ))}
          </ol>
        </section>
      ) : hypotheses.length ? (
        <section className={REPORT_SECTION_CLASSES}>
          <h3 className={REPORT_H3_CLASSES}>Winning ideas</h3>
          <ol className={REPORT_LIST_CLASSES}>
            {[...hypotheses]
              .sort((a, b) => b.elo_rating - a.elo_rating)
              .slice(0, 5)
              .map(hypothesis => (
                <li
                  className={REPORT_SECTION_LIST_ITEM_CLASSES}
                  key={hypothesis.id}
                >
                  <strong>{hypothesis.title}</strong>
                  <span className={REPORT_SECTION_LIST_META_CLASSES}>
                    Elo rating: {hypothesis.elo_rating}
                  </span>
                </li>
              ))}
          </ol>
        </section>
      ) : null}

      <section className={REPORT_SECTION_CLASSES}>
        <h3 className={REPORT_H3_CLASSES}>Tournament summary</h3>
        <p>
          {matches.length
            ? `${matches.length} tournament matches have been recorded for this run.`
            : 'Tournament matches appear here once ranking begins.'}
        </p>
      </section>
    </ReportDocument>
  );
}

/**
 * Builds the reference's lead stat sentence, e.g. "A total of 133 ideas were
 * explored over 3 hours with the highest Elo rating of 1735 points and a total
 * of 1360 matches were played." Clauses whose data is unknown are omitted, and
 * an empty string is returned when there is nothing meaningful to report yet.
 */
function researchOverviewLeadStat({
  run,
  leaderboard,
  hypotheses,
  matches,
}: {
  run: RunWithSummary | null;
  leaderboard: {elo: number}[];
  hypotheses: Hypothesis[];
  matches: MatchRow[];
}): string {
  const ideaCount = hypotheses.length;
  if (!ideaCount) return '';

  const duration = runDurationPhrase(run);
  const highestElo = Math.max(
    0,
    ...leaderboard.map(item => item.elo),
    ...hypotheses.map(hypothesis => hypothesis.elo_rating),
  );
  const matchCount = matches.length;

  const ideaLabel = ideaCount === 1 ? 'idea was' : 'ideas were';
  let sentence = `A total of ${ideaCount} ${ideaLabel} explored`;
  if (duration) sentence += ` over ${duration}`;
  if (highestElo > 0) {
    sentence += ` with the highest Elo rating of ${highestElo} points`;
  }
  if (matchCount > 0) {
    const matchLabel = matchCount === 1 ? 'match was' : 'matches were';
    sentence += ` and a total of ${matchCount} ${matchLabel} played`;
  }
  return `${sentence}.`;
}

/**
 * Formats a run's wall-clock duration (creation to completion) as a rounded
 * human phrase, e.g. "3 hours" or "12 minutes". Returns an empty string when
 * the run has not completed or the timestamps are unusable.
 */
function runDurationPhrase(run: RunWithSummary | null): string {
  if (!run?.completed_at || !run.created_at) return '';
  const seconds = run.completed_at - run.created_at;
  if (!Number.isFinite(seconds) || seconds <= 0) return '';

  if (seconds >= HOUR_SECONDS) {
    const hours = Math.round(seconds / HOUR_SECONDS);
    return `${hours} hour${hours === 1 ? '' : 's'}`;
  }
  const minutes = Math.max(1, Math.round(seconds / MINUTE_SECONDS));
  return `${minutes} minute${minutes === 1 ? '' : 's'}`;
}

/** Curated display title for known domains, or null to fall back to the goal. */
function domainTitleOverride(goal: string): string | null {
  if (/MASH|MASLD|liver fibrosis/i.test(goal)) {
    return 'Epigenetic and stromal reversal strategies for MASH-associated liver fibrosis';
  }
  return null;
}

function RunToast({toast}: {toast: {type: 'info' | 'error'; message: string}}) {
  return (
    <div role="status" className={REPORT_TOAST_CLASSES}>
      {toast.message}
    </div>
  );
}

function normalizeTab(tab: string | undefined): TabName {
  if (!tab) return 'details';
  if ((TABS as readonly string[]).includes(tab)) return tab as TabName;
  return TAB_ALIASES[tab] ?? 'details';
}

function RunDetailSkeleton() {
  return (
    <div className={REPORT_SKELETON_CLASSES} aria-busy="true">
      <div className="wb-skeleton h-8 w-64" />
      <div className="wb-skeleton h-12 w-full" />
      <div className="wb-skeleton h-48 w-full" />
    </div>
  );
}
