import '@material/web/button/outlined-button.js';
import '@material/web/button/text-button.js';
import '@material/web/icon/icon.js';
import {useCallback, useEffect, useMemo, useState} from 'react';
import {Link, useNavigate, useParams} from 'react-router-dom';
import {
  type CitationRow,
  cancelRun,
  type Evidence,
  getCitations,
  getEvidence,
  getHypotheses,
  getMatches,
  getReport,
  getReviews,
  getRun,
  getSafety,
  type Hypothesis,
  type MatchRow,
  type Report,
  type Review,
  type RunWithSummary,
  reportMarkdownUrl,
  type SafetyDecision,
} from '@/api/runs';
import {type StreamEvent, useRunStream} from '@/hooks/useRunStream';
import {useT} from '@/i18n';
import {MdSecondaryTabs} from '@/md3/MdTabs';
import {IdeaModal} from '../components/IdeaModal';
import {RunStatusPill} from '../components/RunStatusPill';
import {ChatTab} from '../components/tabs/ChatTab';
import {EvidenceTab} from '../components/tabs/EvidenceTab';
import {IdeasTab} from '../components/tabs/IdeasTab';
import {OverviewTab} from '../components/tabs/OverviewTab';
import {ReportTab} from '../components/tabs/ReportTab';
import {TournamentTab} from '../components/tabs/TournamentTab';

const TABS = [
  'overview',
  'ideas',
  'evidence',
  'tournament',
  'report',
  'chat',
] as const;
type TabName = (typeof TABS)[number];

const TAB_ICON_NAMES: Record<TabName, string> = {
  overview: 'monitoring',
  ideas: 'format_list_numbered',
  evidence: 'menu_book',
  tournament: 'compare_arrows',
  report: 'description',
  chat: 'chat',
};

const TAB_LABEL_KEYS: Record<TabName, string> = {
  overview: 'runDetail.tab.overview',
  ideas: 'runDetail.tab.ideas',
  evidence: 'runDetail.tab.evidence',
  tournament: 'runDetail.tab.tournament',
  report: 'runDetail.tab.report',
  chat: 'runDetail.tab.chat',
};

/**
 * Renders a single run's tabbed detail view with live streaming updates.
 */
export function RunDetail() {
  const t = useT();
  const {id, tab} = useParams<{id: string; tab?: string}>();
  const navigate = useNavigate();
  const activeTab = (
    tab && (TABS as readonly string[]).includes(tab) ? tab : 'overview'
  ) as TabName;

  const [run, setRun] = useState<RunWithSummary | null>(null);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [safety, setSafety] = useState<SafetyDecision[]>([]);
  const [citations, setCitations] = useState<CitationRow[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [focusedHypId, setFocusedHypId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [toast, setToast] = useState<{
    type: 'info' | 'error';
    message: string;
  } | null>(null);

  const {events, terminal, isOpen} = useRunStream(id ?? null, 0);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      const [r, h, e, m, rv, s, c, rep] = await Promise.all([
        getRun(id),
        getHypotheses(id),
        getEvidence(id),
        getMatches(id),
        getReviews(id),
        getSafety(id),
        getCitations(id),
        getReport(id),
      ]);
      setRun(r);
      setHypotheses(h);
      setEvidence(e);
      setMatches(m);
      setReviews(rv);
      setSafety(s);
      setCitations(c);
      setReport(rep);
      setLoaded(true);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setLoaded(true);
    }
  }, [id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Re-pull on new events so tabs stay in sync.
  useEffect(() => {
    if (!events.length) return;
    const interesting = events[events.length - 1]?.type;
    if (interesting && interesting !== 'status') void refresh();
  }, [events, refresh]);

  useEffect(() => {
    if (terminal) void refresh();
  }, [terminal, refresh]);

  // Toast on terminal status.
  useEffect(() => {
    if (!terminal || !run) return;
    if (run.status === 'completed') {
      setToast({type: 'info', message: t('runDetail.toast.completed')});
      const timer = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(timer);
    }
    if (run.status === 'failed' || run.status === 'blocked') {
      setToast({
        type: 'error',
        message: run.error
          ? t('runDetail.toast.failedWithError', {
              status: run.status,
              error: run.error,
            })
          : t('runDetail.toast.failed', {status: run.status}),
      });
    }
  }, [terminal, run, t]);

  const onCancel = useCallback(async () => {
    if (!id) return;
    try {
      await cancelRun(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [id, refresh]);

  const focusedHypothesis = useMemo(
    () => hypotheses.find(h => h.id === focusedHypId) || null,
    [hypotheses, focusedHypId],
  );

  const onTabChange = useCallback(
    (index: number) => {
      const name = TABS[index];
      if (name) void navigate(`/runs/${id}/${name === 'overview' ? '' : name}`);
    },
    [id, navigate],
  );

  if (!id) return null;

  const isLiveActive = isOpen && !terminal;

  const tabList = TABS.map(name => ({
    label: t(TAB_LABEL_KEYS[name]),
    icon: TAB_ICON_NAMES[name],
  }));

  const activeTabIndex = TABS.indexOf(activeTab);

  return (
    <div className="space-y-4">
      <header className="space-y-3">
        <Link
          to="/runs"
          className="inline-flex items-center gap-1 text-sm hover:underline"
          style={{color: 'var(--md-sys-color-on-surface-variant)'}}
        >
          <md-icon aria-hidden="true" style={{fontSize: '14px'}}>
            arrow_back
          </md-icon>{' '}
          {t('runDetail.header.allRuns')}
        </Link>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1 space-y-2">
            <h1 className="text-2xl font-semibold leading-tight tracking-tight sm:md-typescale-headline-medium">
              {run?.research_goal ?? t('label.loading')}
            </h1>
            <div
              className="flex items-center gap-x-2 gap-y-1 text-sm flex-wrap"
              style={{color: 'var(--md-sys-color-on-surface-variant)'}}
            >
              {run && <RunStatusPill status={run.status} />}
              {run?.is_demo && (
                <span
                  className="inline-block rounded px-1.5 py-0.5 text-xs font-medium"
                  style={{
                    backgroundColor: 'var(--md-sys-color-secondary-container)',
                    color: 'var(--md-sys-color-on-secondary-container)',
                  }}
                >
                  {t('label.example')}
                </span>
              )}
              {run && (
                <span className="inline-flex items-center gap-1">
                  <span className="sm:inline" aria-hidden="true">
                    ·
                  </span>
                  {t('label.profile')}{' '}
                  <strong className="capitalize">{run.profile}</strong>
                </span>
              )}
              {run && (
                <span className="inline-flex items-center gap-1">
                  <span aria-hidden="true">·</span>
                  {t('label.provider')}{' '}
                  <strong className="capitalize">{run.provider}</strong>
                </span>
              )}
              {isLiveActive && (
                <span
                  className="inline-flex items-center gap-1"
                  aria-live="polite"
                >
                  · <span className="wb-live-dot" aria-hidden="true" />{' '}
                  {t('runDetail.header.live')}
                </span>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center sm:flex-wrap">
            <md-outlined-button
              onclick={(() => void refresh()) as EventListener}
            >
              <md-icon slot="icon" aria-hidden="true">
                refresh
              </md-icon>
              {t('runDetail.action.refresh')}
            </md-outlined-button>
            {run?.status === 'running' || run?.status === 'queued' ? (
              <md-outlined-button
                onclick={(() => void onCancel()) as EventListener}
                style={
                  {
                    '--md-outlined-button-outline-color':
                      'var(--md-sys-color-error)',
                    '--md-outlined-button-label-text-color':
                      'var(--md-sys-color-error)',
                  } as React.CSSProperties
                }
              >
                <md-icon slot="icon" aria-hidden="true">
                  stop
                </md-icon>
                {t('action.cancel')}
              </md-outlined-button>
            ) : null}
            {report && (
              <md-outlined-button
                onclick={
                  (() => {
                    const a = document.createElement('a');
                    a.href = reportMarkdownUrl(id);
                    a.download = 'report.md';
                    a.click();
                  }) as EventListener
                }
              >
                <md-icon slot="icon" aria-hidden="true">
                  download
                </md-icon>
                {t('runDetail.action.exportReport')}
              </md-outlined-button>
            )}
          </div>
        </div>
      </header>

      <MdSecondaryTabs
        tabs={tabList}
        activeIndex={activeTabIndex}
        onChange={onTabChange}
      />

      {error && (
        <div
          role="alert"
          className="text-sm rounded border p-2"
          style={{
            borderColor: 'var(--md-sys-color-error)',
            color: 'var(--md-sys-color-error)',
          }}
        >
          {error}
        </div>
      )}

      {!loaded && !error ? (
        <RunDetailSkeleton />
      ) : (
        <div className="wb-fade-in" key={activeTab}>
          {activeTab === 'overview' && (
            <OverviewTab
              run={run}
              hypotheses={hypotheses}
              evidence={evidence}
              matches={matches}
              safety={safety}
              events={events as StreamEvent[]}
            />
          )}
          {activeTab === 'ideas' && (
            <IdeasTab
              hypotheses={hypotheses}
              citations={citations}
              reviews={reviews}
              onFocus={setFocusedHypId}
            />
          )}
          {activeTab === 'evidence' && (
            <EvidenceTab evidence={evidence} citations={citations} />
          )}
          {activeTab === 'tournament' && (
            <TournamentTab matches={matches} hypotheses={hypotheses} />
          )}
          {activeTab === 'report' && (
            <ReportTab runId={id} report={report} safety={safety} />
          )}
          {activeTab === 'chat' && <ChatTab run={run} />}
        </div>
      )}

      {focusedHypothesis && (
        <IdeaModal
          hypothesis={focusedHypothesis}
          allHypotheses={hypotheses}
          reviews={reviews.filter(
            r => r.hypothesis_id === focusedHypothesis.id,
          )}
          citations={citations.filter(
            c => c.hypothesis_id === focusedHypothesis.id,
          )}
          evidence={evidence}
          onClose={() => setFocusedHypId(null)}
        />
      )}

      {toast && (
        <div
          role="status"
          className="fixed bottom-4 left-4 right-4 sm:left-auto sm:right-4 sm:w-auto z-50 rounded border px-3 py-2 text-sm shadow-lg wb-fade-in"
          style={{
            borderColor:
              toast.type === 'error'
                ? 'var(--md-sys-color-error)'
                : 'var(--md-sys-color-outline-variant)',
            backgroundColor: 'var(--md-sys-color-surface-container)',
            color: 'var(--md-sys-color-on-surface)',
          }}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}

function RunDetailSkeleton() {
  return (
    <div className="space-y-3" aria-busy="true">
      <div className="wb-skeleton h-32 w-full" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {['sk-a', 'sk-b', 'sk-c', 'sk-d'].map(k => (
          <div key={k} className="wb-skeleton h-24" />
        ))}
      </div>
      <div className="wb-skeleton h-48 w-full" />
    </div>
  );
}
