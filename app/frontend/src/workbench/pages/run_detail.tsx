import {type ChangeEvent, useEffect, useState} from 'react';
import {useParams} from 'react-router-dom';
import {
  type ClaimEvidenceRow,
  type Evidence,
  type Hypothesis,
  type MatchRow,
  type Report,
  type Review,
  type RunFocus,
  type RunTier,
  type SafetyDecision,
  adjudicateSafety,
  isActiveStatus,
  uploadRunDocument,
  runGoal,
  type RunWithSummary,
} from '@/api/runs';
import {IdeasTab} from '../components/tabs/ideas_tab';
import {FOCUS_OPTIONS, TIER_OPTIONS} from '../run_spec';
import {useRunDetailData} from './run_detail_data';
import {
  REPORT_H3_CLASSES,
  ReportDocument,
  ReportList,
} from './run_detail_document';
import {LearningView} from './run_detail_learning';
import {ResearchOverviewView} from './run_detail_overview';
import {
  ReportErrorAlert,
  ReportTabNav,
  ReportTitlebar,
  RunDetailSkeleton,
  RunToast,
  useTabNavigation,
} from './run_detail_shell';
import {normalizeTab, type TabName} from '../run_tabs';
import {RunExecutionProgress} from './home_recents_run_steps';
import type {StreamEvent} from '@/hooks/use_run_stream';
import {Icon, type IconName} from '@/components/icon';

const REPORT_PAGE_CLASSES =
  'cosci-report-page grid h-full min-h-0 ' +
  'grid-rows-[3.75rem_5rem_minmax(0,1fr)] bg-cosci-bg text-cosci-fg ' +
  'max-[720px]:min-w-0 max-[720px]:overflow-hidden';

const REPORT_SCROLL_CLASSES =
  'cosci-report-scroll min-h-0 overflow-auto max-[720px]:overflow-x-hidden';

const ALL_IDEAS_CLASSES = 'cosci-all-ideas h-full p-0 max-[720px]:h-auto';

/**
 * Renders the Co-Scientist goal report surface from the reference footage.
 */
export function RunDetail() {
  const {id, tab} = useParams<{id: string; tab?: string}>();
  const activeTab = normalizeTab(tab);
  const {ideasViewKey, onTabChange} = useTabNavigation(id, activeTab);

  const {
    run,
    hypotheses,
    evidence,
    matches,
    reviews,
    claimEvidence,
    report,
    safety,
    error,
    loaded,
    toast,
    title,
    refreshNow,
    events,
  } = useRunDetailData(id);

  if (!id) return null;

  const active = isActiveStatus(run?.status);
  const pageClasses = active
    ? `${REPORT_PAGE_CLASSES} grid-rows-[3.75rem_minmax(0,1fr)]`
    : REPORT_PAGE_CLASSES;
  return (
    <div className={pageClasses}>
      <ReportTitlebar title={title} />

      {!active && (
        <ReportTabNav activeTab={activeTab} onTabChange={onTabChange} />
      )}

      <ReportErrorAlert message={error} />

      {!loaded && !error ? (
        <RunDetailSkeleton />
      ) : active && run ? (
        <ActiveRunView
          run={run}
          events={events}
          evidenceCount={Math.max(evidence.length, run.summary.evidence)}
          ideaCount={Math.max(hypotheses.length, run.summary.hypotheses)}
        />
      ) : (
        <RunDetailTabContent
          activeTab={activeTab}
          run={run}
          evidence={evidence}
          report={report}
          hypotheses={hypotheses}
          matches={matches}
          reviews={reviews}
          claimEvidence={claimEvidence}
          safety={safety}
          onSafetyChanged={refreshNow}
          ideasViewKey={ideasViewKey}
        />
      )}

      {toast && <RunToast message={toast} />}
    </div>
  );
}

function ActiveRunView({
  run,
  events,
  evidenceCount,
  ideaCount,
}: {
  run: RunWithSummary;
  events: StreamEvent[];
  evidenceCount: number;
  ideaCount: number;
}) {
  // Ticks so relative timestamps and the elapsed clock stay honest even while
  // a slow node holds the run without emitting a new event.
  const nowSeconds = useNowTick(30_000);
  const elapsedSeconds = Math.max(0, Math.round(nowSeconds - run.created_at));
  const fraction = run.execution_progress?.fraction;
  const remainingSeconds =
    run.execution_progress?.determinate && fraction && fraction > 0
      ? Math.max(0, Math.round((elapsedSeconds * (1 - fraction)) / fraction))
      : null;
  const activity = events
    .filter(event => event.type !== 'status')
    .slice(-10)
    .reverse();
  return (
    <main className="min-h-0 overflow-auto px-8 py-7 max-[720px]:px-4">
      <section className="mx-auto grid w-full max-w-4xl gap-7">
        <div>
          <p className="text-sm font-medium text-cosci-blue">Executing</p>
          <h2 className="mt-1 text-2xl font-medium">Research in progress</h2>
          <RunExecutionProgress run={run} />
        </div>
        <dl className="grid grid-cols-3 gap-3 max-[720px]:grid-cols-1">
          <RunMetric
            label="Time remaining"
            value={
              remainingSeconds === null ? 'Estimating…' : `${remainingSeconds}s`
            }
          />
          <RunMetric label="Sources Analyzed" value={String(evidenceCount)} />
          <RunMetric label="Ideas explored" value={String(ideaCount)} />
        </dl>
        <section aria-label="Activity log">
          <div className="flex items-center gap-2.5">
            <LivePulse />
            <h3 className="text-base font-medium">Live activity</h3>
          </div>
          {activity.length ? (
            <ol className="mt-5">
              {activity.map((event, index) => (
                <ActivityItem
                  key={event.seq}
                  event={event}
                  isLatest={index === 0}
                  isLast={index === activity.length - 1}
                  now={nowSeconds}
                />
              ))}
            </ol>
          ) : (
            <div className="mt-4 flex items-center gap-3 rounded-md bg-cosci-hover px-4 py-3.5">
              <span className="size-2 shrink-0 animate-pulse rounded-full bg-cosci-muted" />
              <p className="text-sm text-cosci-muted">
                Warming up — the first steps will appear here in a moment.
              </p>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}

function RunMetric({label, value}: {label: string; value: string}) {
  return (
    <div className="rounded-md bg-cosci-hover p-4">
      <dt className="text-xs text-cosci-muted">{label}</dt>
      <dd className="mt-1 text-xl font-medium">{value}</dd>
    </div>
  );
}

// Per-phase icon + accent tone for the live-activity timeline, keyed by the
// base node name (the part before any dotted qualifier, e.g. supervisor.plan).
const ACTIVITY_VISUALS: Record<string, {icon: IconName; tone: string}> = {
  bootstrap: {icon: 'settings', tone: 'text-cosci-muted'},
  created: {icon: 'check', tone: 'text-cosci-muted'},
  queued: {icon: 'history', tone: 'text-cosci-muted'},
  completed: {icon: 'check', tone: 'text-th-success'},
  supervisor: {icon: 'assignment', tone: 'text-th-primary'},
  orchestrator: {icon: 'assignment', tone: 'text-th-primary'},
  literature_review: {icon: 'menu_book', tone: 'text-cosci-teal'},
  generate: {icon: 'lightbulb', tone: 'text-th-primary'},
  reflection: {icon: 'neurology', tone: 'text-th-success'},
  comprehensive_reflection: {icon: 'neurology', tone: 'text-th-success'},
  review: {icon: 'rate_review', tone: 'text-th-success'},
  deep_verification: {icon: 'check', tone: 'text-th-success'},
  ranking: {icon: 'emoji_events', tone: 'text-th-warning'},
  meta_review: {icon: 'summarize', tone: 'text-th-primary'},
  research_overview: {icon: 'stars', tone: 'text-th-primary'},
  evolve: {icon: 'edit_square', tone: 'text-cosci-blue'},
  proximity: {icon: 'chess', tone: 'text-cosci-teal'},
  safety_screen: {icon: 'encrypted', tone: 'text-th-warning'},
  safety: {icon: 'encrypted', tone: 'text-th-warning'},
};

// Human-readable phase titles for the same keys.
const PHASE_TITLES: Record<string, string> = {
  bootstrap: 'Initializing run',
  created: 'Run created',
  queued: 'Queued',
  completed: 'Run complete',
  supervisor: 'Planning strategy',
  orchestrator: 'Coordinating agents',
  literature_review: 'Reviewing literature',
  generate: 'Generating hypotheses',
  reflection: 'Reflecting on ideas',
  comprehensive_reflection: 'Deep reflection',
  review: 'Reviewing hypotheses',
  deep_verification: 'Verifying assumptions',
  ranking: 'Ranking tournament',
  meta_review: 'Synthesizing meta-review',
  research_overview: 'Building research overview',
  evolve: 'Evolving hypotheses',
  proximity: 'Mapping the idea landscape',
  safety_screen: 'Safety screening',
  safety: 'Safety screening',
};

const DEFAULT_ACTIVITY_VISUAL = {
  icon: 'history' as IconName,
  tone: 'text-cosci-muted',
};

// The phase a step represents. scientific_task events carry the engine node in
// payload.task and lifecycle events carry it in payload.event; other kinds
// (e.g. safety.intake) are named by their own dotted type.
function activityPhase(event: StreamEvent): string {
  if (event.type === 'scientific_task') return String(event.payload.task ?? '');
  if (event.type === 'lifecycle') return String(event.payload.event ?? '');
  return event.type.split('.')[0] ?? event.type;
}

function activityVisual(phase: string): {icon: IconName; tone: string} {
  return ACTIVITY_VISUALS[phase] ?? DEFAULT_ACTIVITY_VISUAL;
}

function phaseTitle(phase: string): string {
  const known = PHASE_TITLES[phase];
  if (known) return known;
  const words = phase.replaceAll('_', ' ').replaceAll('.', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// A human detail line when the event carries one (a message or a safety
// rationale). Phase-only steps render just their title and timestamp; the task
// field is the phase itself, so it never doubles as the detail.
function activityDetail(event: StreamEvent): string {
  const detail = event.payload.message || event.payload.reason;
  return detail ? String(detail) : '';
}

// Compact relative age of an event, e.g. "just now", "8s ago", "2m ago".
function relativeTime(createdAt: number | undefined, now: number): string {
  if (!createdAt) return '';
  const seconds = Math.max(0, Math.round(now - createdAt));
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}

// Re-renders the caller on an interval so time-based UI (relative timestamps,
// the elapsed clock) advances even when no new events or props arrive.
function useNowTick(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

// A small sonar dot signalling the feed is live.
function LivePulse() {
  return (
    <span className="relative flex size-2.5" aria-hidden="true">
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-th-primary" />
      <span className="relative inline-flex size-2.5 rounded-full bg-th-primary" />
    </span>
  );
}

// One node in the vertical activity timeline: a phase icon on the connector
// rail, then the phase title, its detail, and how long ago it landed. The most
// recent step is filled and gently pulses so it reads as "happening now".
function ActivityItem({
  event,
  isLatest,
  isLast,
  now,
}: {
  event: StreamEvent;
  isLatest: boolean;
  isLast: boolean;
  now: number;
}) {
  const phase = activityPhase(event);
  const {icon, tone} = activityVisual(phase);
  const detail = activityDetail(event);
  return (
    <li className="relative flex gap-4 pb-6 last:pb-0">
      {!isLast && (
        <span
          aria-hidden="true"
          className="absolute left-[1.0625rem] top-[2.375rem] bottom-1 w-px bg-cosci-border"
        />
      )}
      <span
        className={[
          'relative z-[1] grid size-[2.125rem] shrink-0 place-items-center',
          'rounded-full',
          isLatest ? 'animate-pulse bg-th-primary' : 'bg-cosci-hover',
        ].join(' ')}
      >
        <Icon
          name={icon}
          className={[
            'text-[1.15rem]',
            isLatest ? 'text-th-primary-fg' : tone,
          ].join(' ')}
        />
      </span>
      <div className="min-w-0 flex-1">
        {/* Sized to the disc and centred against it, so the title sits on the
            disc's axis rather than being nudged by a fixed amount. Both
            paragraphs zero their margins: <p> keeps its user-agent margins
            here (only div is reset), and 16px of it above the title is what
            pushed the row past the disc and off-centre. */}
        <div className="flex min-h-[2.125rem] items-center justify-between gap-3">
          <p className="my-0 truncate font-medium text-cosci-fg">
            {phaseTitle(phase)}
          </p>
          <span className="shrink-0 text-xs text-cosci-muted">
            {relativeTime(event.created_at, now)}
          </span>
        </div>
        {detail ? (
          <p className="mb-0 mt-0.5 line-clamp-2 text-sm text-cosci-muted">
            {detail}
          </p>
        ) : null}
      </div>
    </li>
  );
}

// Active tab content for a loaded run. Keying <main> by activeTab remounts it
// on tab switch, which also resets any per-tab local UI state (e.g.
// IdeasTab's selection, LearningView's search query).
function RunDetailTabContent({
  activeTab,
  run,
  evidence,
  report,
  hypotheses,
  matches,
  reviews,
  claimEvidence,
  safety,
  onSafetyChanged,
  ideasViewKey,
}: {
  activeTab: TabName;
  run: RunWithSummary | null;
  evidence: Evidence[];
  report: Report | null;
  hypotheses: Hypothesis[];
  matches: MatchRow[];
  reviews: Review[];
  claimEvidence: ClaimEvidenceRow[];
  safety: SafetyDecision[];
  onSafetyChanged: () => void;
  ideasViewKey: number;
}) {
  return (
    <main className={REPORT_SCROLL_CLASSES} key={activeTab}>
      {activeTab === 'details' && (
        <RunSpecificationsView
          run={run}
          safety={safety}
          onSafetyChanged={onSafetyChanged}
        />
      )}
      {activeTab === 'learning' && (
        <LearningView goal={runGoal(run)} evidence={evidence} report={report} />
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
            claimEvidence={claimEvidence}
          />
        </section>
      )}
    </main>
  );
}

// Requirements/attributes/criteria captured in a run's durable setup config,
// each defaulted to an empty list when the run has no setup yet.
function goalDetailsLists(setup: RunWithSummary['config']['setup']): {
  requirements: string[];
  attributes: string[];
  criteria: string[];
} {
  if (!setup) return {requirements: [], attributes: [], criteria: []};
  return {
    requirements: setup.requirements,
    attributes: setup.attributes,
    criteria: setup.criteria,
  };
}

// Human-readable label for a stored run tier/focus, falling back to the
// default when the value is missing or a legacy value.
function tierLabel(tier: RunTier | undefined): string {
  return TIER_OPTIONS.find(option => option.id === tier)?.label ?? 'Standard';
}

function focusLabel(focus: RunFocus | undefined): string {
  return FOCUS_OPTIONS.find(option => option.id === focus)?.label ?? 'Balance';
}

// Run Specifications preserves the final interview contract and run mode.
function RunSpecificationsView({
  run,
  safety,
  onSafetyChanged,
}: {
  run: RunWithSummary | null;
  safety: SafetyDecision[];
  onSafetyChanged: () => void;
}) {
  const goal = runGoal(run) || 'Loading...';
  const {requirements, attributes, criteria} = goalDetailsLists(
    run?.config.setup,
  );

  return (
    <ReportDocument
      title="Run Specifications"
      className="cosci-run-specifications"
    >
      <p>
        <strong>Research Challenge:</strong> {goal}
      </p>
      <ReportList title="Focus Area" values={attributes} />
      <ReportList title="Preferences" values={requirements} />
      <p>
        <strong>Title:</strong> {run?.title || 'Optional'}
      </p>
      <p>
        <strong>Run type:</strong> {tierLabel(run?.config.tier)}
      </p>
      <p>
        <strong>Focus:</strong> {focusLabel(run?.config.focus)}
      </p>
      {criteria.length > 0 && (
        <p>
          <strong>Reconstruction provenance:</strong> Legacy criteria are
          retained in the stored run but are not part of the four-field Agent
          interview contract.
        </p>
      )}
      <SafetyReviewSection
        runId={run?.id}
        decisions={safety}
        onChanged={onSafetyChanged}
      />
      <PrivateCorpusUpload runId={run?.id} onChanged={onSafetyChanged} />
    </ReportDocument>
  );
}

function PrivateCorpusUpload({
  runId,
  onChanged,
}: {
  runId: string | undefined;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !runId) return;
    setBusy(true);
    setStatus(null);
    try {
      const result = await uploadRunDocument(runId, file);
      setStatus(
        `${file.name} indexed (${result.byte_size.toLocaleString()} bytes).`,
      );
      onChanged();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Private research sources</h3>
      <p>
        Upload a PDF or UTF-8 text, Markdown, CSV, or JSON document. It remains
        scoped to this run and is indexed for subsequent scientific tasks.
      </p>
      <label className="mt-3 inline-flex cursor-pointer rounded-full border border-cosci-border px-4 py-2 text-sm hover:bg-cosci-hover">
        {busy ? 'Indexing…' : 'Upload document'}
        <input
          type="file"
          className="sr-only"
          accept=".pdf,.txt,.md,.csv,.json,application/pdf,text/plain,text/markdown,text/csv,application/json"
          disabled={busy || !runId}
          onChange={event => void upload(event)}
        />
      </label>
      {status && (
        <p role="status" className="mt-2 text-sm">
          {status}
        </p>
      )}
    </section>
  );
}

function SafetyReviewSection({
  runId,
  decisions,
  onChanged,
}: {
  runId: string | undefined;
  decisions: SafetyDecision[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const reviewable = decisions.filter(
    decision => decision.requires_review && !decision.resolution,
  );
  if (!decisions.length) return null;

  async function resolve(
    decision: SafetyDecision,
    resolution: 'approved' | 'rejected',
  ) {
    if (!runId) return;
    setBusy(decision.id);
    try {
      await adjudicateSafety(runId, decision.id, resolution);
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Safety audit</h3>
      {decisions.map(decision => (
        <div className="mb-5" key={decision.id}>
          <p>
            <strong>{decision.stage}:</strong>{' '}
            {decision.category || decision.decision} — {decision.reason}
          </p>
          <p className="text-sm text-cosci-muted">
            Policy {decision.policy_version || 'legacy'} ·{' '}
            {decision.assessor || 'deterministic'}
          </p>
          {decision.resolution ? (
            <p>Resolution: {decision.resolution}</p>
          ) : null}
          {reviewable.includes(decision) ? (
            <div className="flex gap-2">
              <button
                className="rounded-full border border-cosci-border px-4 py-2"
                disabled={busy === decision.id}
                onClick={() => void resolve(decision, 'approved')}
                type="button"
              >
                Approve for research use
              </button>
              <button
                className="rounded-full border border-cosci-border px-4 py-2"
                disabled={busy === decision.id}
                onClick={() => void resolve(decision, 'rejected')}
                type="button"
              >
                Reject
              </button>
            </div>
          ) : null}
        </div>
      ))}
    </section>
  );
}
