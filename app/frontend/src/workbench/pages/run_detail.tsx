import '@material/web/icon/icon.js';
import {useCallback, useEffect, useMemo, useState, type ReactNode} from 'react';
import {Link, useNavigate, useParams} from 'react-router-dom';
import {
  type CitationRow,
  type Evidence,
  getCitations,
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
  type RunSetupConfig,
  type RunWithSummary,
} from '@/api/runs';
import {useRunStream} from '@/hooks/use_run_stream';
import {conciseTitle} from '@/lib/text';
import {IdeasTab} from '../components/tabs/ideas_tab';

const TABS = ['details', 'learning', 'overview', 'ideas'] as const;
type TabName = (typeof TABS)[number];

const TAB_ICON_NAMES: Record<TabName, string> = {
  details: 'menu_book',
  learning: 'menu_book',
  overview: 'view_list',
  ideas: 'emoji_objects',
};

const TAB_LABELS: Record<TabName, string> = {
  details: 'Goal Details',
  learning: 'Learning',
  overview: 'Research Overview',
  ideas: 'All Ideas',
};

const REPORT_PAGE_CLASSES =
  'cosci-report-page grid h-full min-h-0 grid-rows-[4.75rem_5.5rem_minmax(0,1fr)] bg-[var(--cosci-bg)] text-[var(--cosci-text)] max-[720px]:min-w-0 max-[720px]:overflow-hidden';

const REPORT_TITLEBAR_CLASSES =
  'cosci-report-titlebar flex min-w-0 items-center justify-between gap-6 border-b border-[var(--cosci-border)] px-9 max-[720px]:gap-[0.35rem] max-[720px]:px-[0.7rem]';

const REPORT_TITLE_LEFT_CLASSES =
  'cosci-report-title-left flex min-w-0 items-center gap-4 max-[720px]:gap-[0.45rem]';

const REPORT_BACK_CLASSES =
  'cosci-report-back grid h-10 w-10 shrink-0 place-items-center rounded-full text-[var(--cosci-muted)] no-underline hover:bg-[var(--cosci-hover)]';

const REPORT_TITLE_CLASSES =
  'm-0 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-[1.2rem] leading-[1.25] font-normal tracking-normal max-[720px]:text-[0.9rem]';

const SESSION_DETAILS_CLASSES =
  'cosci-session-details cursor-pointer border-0 bg-transparent px-0 py-[0.45rem] font-[inherit] text-sm font-medium text-[var(--cosci-blue)] max-[720px]:hidden';

const REPORT_TABS_CLASSES =
  'cosci-report-tabs grid grid-cols-4 border-b border-[var(--cosci-border)] max-[720px]:min-w-0 max-[720px]:overflow-x-hidden';

const REPORT_TAB_BUTTON_BASE_CLASSES =
  'relative grid min-w-0 cursor-pointer content-center justify-items-center gap-[0.35rem] border-0 bg-transparent font-[inherit] text-sm max-[720px]:gap-[0.2rem] max-[720px]:text-[0.68rem]';

const REPORT_TAB_SELECTED_CLASSES =
  "text-[var(--cosci-blue)] after:absolute after:right-[1.1rem] after:bottom-0 after:left-[1.1rem] after:h-[0.18rem] after:rounded-t-full after:bg-[var(--cosci-blue-strong)] after:content-['']";

const REPORT_TAB_ICON_CLASSES = 'text-[1.35rem] max-[720px]:text-[1.12rem]';

const REPORT_TAB_LABEL_CLASSES = 'max-[720px]:text-[0.75rem]';

const REPORT_SCROLL_CLASSES =
  'cosci-report-scroll min-h-0 overflow-auto max-[720px]:overflow-x-hidden';

const REPORT_ALERT_CLASSES =
  'cosci-report-alert mx-8 mt-4 rounded-xl border border-[#b3261e] bg-[#fce8e6] px-4 py-3 text-[#b3261e] dark:border-[#5b2b2b] dark:bg-[#3c1715] dark:text-[#ffb4aa]';

const REPORT_TOAST_CLASSES =
  'cosci-report-toast fixed right-4 bottom-4 z-50 rounded-xl border border-[#b3261e] bg-[#fce8e6] px-4 py-3 text-[#b3261e] dark:border-[#5b2b2b] dark:bg-[#3c1715] dark:text-[#ffb4aa]';

const REPORT_SKELETON_CLASSES =
  'cosci-report-skeleton mx-auto my-9 grid w-[min(100%_-_3rem,58rem)] gap-4 max-[720px]:mt-5 max-[720px]:mb-12 max-[720px]:w-[min(100%_-_1.2rem,100%)] max-[720px]:max-w-none';

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
 * Renders the AI Co-Scientist goal report surface from the reference footage.
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
  const [citations, setCitations] = useState<CitationRow[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [toast, setToast] = useState<{
    type: 'info' | 'error';
    message: string;
  } | null>(null);

  const {events, terminal} = useRunStream(id ?? null, 0);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      const [r, h, e, m, rv, c, rep] = await Promise.all([
        getRun(id),
        getHypotheses(id),
        getEvidence(id),
        getMatches(id),
        getReviews(id),
        getCitations(id),
        getReport(id),
      ]);
      setRun(r);
      setHypotheses(h);
      setEvidence(e);
      setMatches(m);
      setReviews(rv);
      setCitations(c);
      setReport(rep);
      setLoaded(true);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoaded(true);
    }
  }, [id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!events.length) return;
    const interesting = events[events.length - 1]?.type;
    if (interesting && interesting !== 'status') void refresh();
  }, [events, refresh]);

  useEffect(() => {
    if (terminal) void refresh();
  }, [terminal, refresh]);

  useEffect(() => {
    if (!terminal || !run) return;
    if (run.status === 'failed' || run.status === 'blocked') {
      setToast({
        type: 'error',
        message: `Run ${run.status}${run.error ? `: ${run.error}` : ''}`,
      });
    }
  }, [terminal, run]);

  const title = useMemo(() => {
    if (!run) return 'Goal report';
    return goalReportTitle(run.research_goal, run.config.setup);
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
      void navigate(`/runs/${id}${nextTab === 'details' ? '' : `/${nextTab}`}`);
    },
    [id, navigate],
  );

  const onSessionDetails = useCallback(() => {
    if (!id) return;
    if (activeTab !== 'details') {
      void navigate(`/runs/${id}`);
      return;
    }
    document.querySelector('.cosci-report-scroll')?.scrollTo({
      top: 0,
      behavior: 'smooth',
    });
  }, [activeTab, id, navigate]);

  if (!id) return null;

  const activeTabIndex = TABS.indexOf(activeTab);

  return (
    <div className={REPORT_PAGE_CLASSES}>
      <header className={REPORT_TITLEBAR_CLASSES}>
        <div className={REPORT_TITLE_LEFT_CLASSES}>
          <Link to="/" className={REPORT_BACK_CLASSES} aria-label="Back">
            <md-icon aria-hidden="true">arrow_back</md-icon>
          </Link>
          <h1 className={REPORT_TITLE_CLASSES}>{title}</h1>
        </div>
        <button
          type="button"
          className={SESSION_DETAILS_CLASSES}
          onClick={onSessionDetails}
        >
          Session details
        </button>
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
            <md-icon className={REPORT_TAB_ICON_CLASSES} aria-hidden="true">
              {TAB_ICON_NAMES[tabName]}
            </md-icon>
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
              report={report}
              hypotheses={hypotheses}
              matches={matches}
            />
          )}
          {activeTab === 'ideas' && (
            <section className="cosci-all-ideas">
              <IdeasTab
                hypotheses={hypotheses}
                citations={citations}
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
    selected ? REPORT_TAB_SELECTED_CLASSES : 'text-[var(--cosci-muted)]'
  }`;
}

function GoalDetailsView({run}: {run: RunWithSummary | null}) {
  const setup = run?.config.setup;
  const goal = setup?.goal ?? run?.research_goal ?? 'Loading...';

  return (
    <article className="cosci-report-document cosci-goal-details">
      <div className="cosci-generated-chip">
        <span aria-hidden="true">-</span>
        Generated by Co-Scientist - Version: March 16 2026
      </div>
      <h2>Research goal details</h2>
      <h3>{goalReportTitle(goal, setup)}</h3>
      <p>
        <strong>Goal:</strong> {goal}
      </p>
      <ReportList title="Requirements" values={setup?.requirements ?? []} />
      <ReportList title="Attributes" values={setup?.attributes ?? []} />
      <ReportList title="Criteria" values={setup?.criteria ?? []} />
    </article>
  );
}

function LearningView({goal, evidence}: {goal: string; evidence: Evidence[]}) {
  const [query, setQuery] = useState('');
  const [expandedSectionIds, setExpandedSectionIds] = useState<string[]>([]);
  const sections = learningSections(goal, evidence);
  const filteredReferences = evidence.filter(item => {
    const haystack = `${item.title} ${item.source} ${item.authors.join(' ')}`;
    return haystack.toLowerCase().includes(query.trim().toLowerCase());
  });
  function toggleSection(sectionId: string) {
    setExpandedSectionIds(current =>
      current.includes(sectionId)
        ? current.filter(id => id !== sectionId)
        : [...current, sectionId],
    );
  }

  return (
    <ReportDocument title="Learning">
      {sections.map(section => {
        const expanded = expandedSectionIds.includes(section.id);
        return (
          <section
            key={section.id}
            id={section.id}
            className="cosci-overview-section"
          >
            <h3>{section.title}</h3>
            <h4>Summary</h4>
            <p>{section.summary}</p>
            {expanded && (
              <>
                <h4>Details</h4>
                <p>{section.detail}</p>
              </>
            )}
            <button
              type="button"
              className="cosci-inline-action"
              aria-expanded={expanded}
              onClick={() => toggleSection(section.id)}
            >
              <span>{expanded ? 'Show less' : 'Show more'}</span>
              <md-icon aria-hidden="true">
                {expanded ? 'expand_less' : 'expand_more'}
              </md-icon>
            </button>
          </section>
        );
      })}
      <ReferencesBlock
        evidence={filteredReferences}
        query={query}
        onQueryChange={setQuery}
      />
    </ReportDocument>
  );
}

function ReferencesBlock({
  evidence,
  query,
  onQueryChange,
}: {
  evidence: Evidence[];
  query: string;
  onQueryChange: (value: string) => void;
}) {
  return (
    <section className="cosci-overview-section cosci-reference-list">
      <h3>References</h3>
      <label className="cosci-reference-search">
        <md-icon aria-hidden="true">search</md-icon>
        <input
          value={query}
          onChange={event => onQueryChange(event.currentTarget.value)}
          placeholder="Search references"
          aria-label="Search references"
        />
      </label>
      <ol>
        {evidence.length ? (
          evidence.map((item, index) => (
            <li key={item.id}>
              <span>[{index + 1}]</span>
              <strong>{item.title}</strong>
              {item.url ? (
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  <md-icon aria-hidden="true">open_in_new</md-icon>
                  Open
                </a>
              ) : null}
            </li>
          ))
        ) : (
          <li>
            <span>[0]</span>
            <strong>No references match the current search.</strong>
          </li>
        )}
      </ol>
    </section>
  );
}

function learningSections(goal: string, evidence: Evidence[]) {
  const fallbackGoal =
    goal ||
    'the biological mechanisms and experimental systems relevant to this research goal';
  const seedEvidence = evidence.length
    ? evidence
    : [
        {
          id: 'learning-fallback',
          title: 'Research context and technical definitions',
          abstract:
            'Co-Scientist is assembling the terminology, methods, and biological context needed to evaluate the research goal.',
          source: 'Co-Scientist',
          authors: ['Co-Scientist'],
          year: null,
          url: '',
          available: false,
        },
      ];

  return seedEvidence.slice(0, 3).map((item, index) => ({
    id: `learning-section-${index + 1}`,
    title: learningTitle(item.title, index),
    summary:
      item.abstract ||
      `This section summarizes the concepts, protocols, and methodological constraints Co-Scientist learned while studying ${fallbackGoal}.`,
    detail:
      item.source && item.year
        ? `Source context: ${item.source}, ${item.year}. Co-Scientist keeps this learning available for downstream hypothesis generation, ranking, and synthesis.`
        : `Co-Scientist keeps this learning available for downstream hypothesis generation, ranking, and synthesis for ${fallbackGoal}.`,
  }));
}

function learningTitle(title: string, index: number): string {
  const cleaned = title.replace(/^H\d+:\s*/i, '').trim();
  if (!cleaned) return `Learning Section ${index + 1}`;
  return cleaned
    .split(/\s+/)
    .map(word =>
      /^(and|or|the|of|in|for|to|with|by)$/i.test(word)
        ? word.toLowerCase()
        : word.charAt(0).toUpperCase() + word.slice(1),
    )
    .join(' ');
}

function ResearchOverviewView({
  report,
  hypotheses,
  matches,
}: {
  report: Report | null;
  hypotheses: Hypothesis[];
  matches: MatchRow[];
}) {
  const overview = report?.payload.research_overview;
  const leaderboard = report?.payload.leaderboard ?? [];

  return (
    <ReportDocument title="Research overview">
      {overview?.overview?.summary ? (
        <p>{overview.overview.summary}</p>
      ) : (
        <p>
          The research overview appears after Co-Scientist finishes the final
          synthesis step.
        </p>
      )}

      {overview?.overview?.research_directions?.length ? (
        <section className="cosci-overview-section">
          <h3>Research directions</h3>
          {overview.overview.research_directions.map(direction => (
            <div key={direction.title}>
              <h4>{direction.title}</h4>
              <p>{direction.importance}</p>
              {direction.suggested_experiments.length ? (
                <ul>
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
        <section className="cosci-overview-section">
          <h3>Specific aims</h3>
          {overview.nih_specific_aims.introduction ? (
            <p>{overview.nih_specific_aims.introduction}</p>
          ) : null}
          {overview.nih_specific_aims.aims.map(aim => (
            <div key={aim.aim}>
              <h4>{aim.aim}</h4>
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
        <section className="cosci-overview-section">
          <h3>Top ideas</h3>
          <ol>
            {leaderboard.slice(0, 5).map(item => (
              <li key={item.id}>
                <strong>{item.title}</strong>
                <span>Elo rating: {item.elo}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : hypotheses.length ? (
        <section className="cosci-overview-section">
          <h3>Top ideas</h3>
          <ol>
            {[...hypotheses]
              .sort((a, b) => b.elo_rating - a.elo_rating)
              .slice(0, 5)
              .map(hypothesis => (
                <li key={hypothesis.id}>
                  <strong>{hypothesis.title}</strong>
                  <span>Elo rating: {hypothesis.elo_rating}</span>
                </li>
              ))}
          </ol>
        </section>
      ) : null}

      <section className="cosci-overview-section">
        <h3>Tournament summary</h3>
        <p>
          {matches.length
            ? `${matches.length} tournament matches have been recorded for this run.`
            : 'Tournament matches appear here once ranking begins.'}
        </p>
      </section>
    </ReportDocument>
  );
}

function ReportDocument({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <article className="cosci-report-document">
      <div className="cosci-generated-chip">
        <span aria-hidden="true">-</span>
        Generated by Co-Scientist - Version: March 16 2026
      </div>
      <h2>{title}</h2>
      {children}
    </article>
  );
}

function ReportList({title, values}: {title: string; values: string[]}) {
  if (!values.length) return null;
  return (
    <section className="cosci-report-list">
      <h4>{title}:</h4>
      <ul>
        {values.map(value => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </section>
  );
}

function goalReportTitle(goal: string, setup?: RunSetupConfig): string {
  if (/MASH|MASLD|liver fibrosis/i.test(goal)) {
    return 'Epigenetic and stromal reversal strategies for MASH-associated liver fibrosis';
  }
  return conciseTitle(setup?.goal ?? goal);
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
