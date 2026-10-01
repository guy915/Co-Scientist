import {useCallback, useState} from 'react';
import {Link, useParams, useSearchParams} from 'react-router-dom';
import {isCancelledStatus, type TerminalNonCompletedStatus} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {TruncatedLabel} from '../components/truncated_label';
import {useIsMobile} from '../hooks/use_is_mobile';
import {tabPath, type TabName} from '../run_tabs';
import {
  REPORT_DOCUMENT_CLASSES,
  REPORT_H2_CLASSES,
} from './run_detail_document';
import {runFailureGuidance} from './run_failure_guidance';

// Icon and label shown per tab in the nav bar (keyed by TabName so a missing
// entry is a compile error, not a silent blank tab). `short` is the label
// narrow phones show: four full labels run together below ~420px.
const TAB_META: Record<
  TabName,
  {icon: IconName; label: string; short: string}
> = {
  details: {icon: 'assignment', label: 'Goal Details', short: 'Details'},
  learning: {icon: 'menu_book', label: 'Learning', short: 'Learning'},
  overview: {icon: 'summarize', label: 'Research Overview', short: 'Overview'},
  ideas: {icon: 'lightbulb', label: 'All Ideas', short: 'Ideas'},
};

/**
 * Accessible name for a tab's content region, matching the label shown for
 * it in the nav strip. `ReportTabNav` is a `<nav>` of real, deep-linkable
 * `<Link>`s (not a tablist) so the content below carries no `aria-controls`/
 * `role="tabpanel"` relationship to it -- but a screen-reader user landing
 * in the region still needs to know which section they arrived in, hence
 * this label rather than that wiring.
 */
export function reportSectionLabel(tab: TabName): string {
  return TAB_META[tab].label;
}

const REPORT_TITLEBAR_CLASSES =
  'cosci-report-titlebar flex min-w-0 items-center justify-between gap-6 ' +
  'border-b border-cosci-border px-9 max-[700px]:gap-[0.35rem] ' +
  'max-[700px]:px-[0.7rem]';

const REPORT_TITLE_LEFT_CLASSES =
  'cosci-report-title-left flex min-w-0 items-center gap-4 ' +
  'max-[700px]:gap-[0.45rem]';

const REPORT_BACK_CLASSES =
  'cosci-report-back grid h-10 w-10 shrink-0 ' +
  'place-items-center rounded-full text-cosci-muted ' +
  'no-underline hover:bg-cosci-hover';

const REPORT_TITLE_CLASSES =
  'm-0 min-w-0 overflow-hidden text-[1.2rem] leading-[1.25] ' +
  'font-normal tracking-normal max-[700px]:text-[0.9rem]';

const REPORT_TITLE_TEXT_CLASSES =
  'block min-w-0 overflow-hidden whitespace-nowrap';

const REPORT_TABS_CLASSES =
  'reference-report-tabs grid grid-cols-4 border-b border-cosci-border ' +
  'max-[700px]:min-w-0 max-[700px]:overflow-x-hidden';

// The tabs are anchors (so a middle/cmd-click opens the tab in a new browser
// tab), hence the explicit no-underline: everything else here matches the
// buttons they replaced. `reference-report-tab` is the hook the hover/focus
// state layer in index.css keys on -- it must stay on whatever element the
// tab is rendered as.
const REPORT_TAB_BUTTON_BASE_CLASSES =
  'reference-report-tab relative grid min-w-0 cursor-pointer content-center ' +
  'justify-items-center gap-[0.35rem] border-0 bg-transparent ' +
  'font-[inherit] text-sm no-underline max-[700px]:gap-[0.2rem] ' +
  'max-[700px]:text-[0.68rem]';

const REPORT_TAB_SELECTED_CLASSES =
  'text-cosci-blue after:absolute after:right-[1.1rem] after:bottom-0 ' +
  'after:left-[1.1rem] after:h-[0.18rem] after:rounded-t-full ' +
  "after:bg-cosci-blue-strong after:content-['']";

const REPORT_TAB_ICON_CLASSES =
  'text-[1.35rem] max-[700px]:text-[1.12rem] ' +
  '[@media(max-height:500px)]:hidden';

// min-w-0/overflow-hidden/whitespace-nowrap constrain the axis TruncatedLabel
// measures against (see its own docstring); without them it has nothing to
// fit to and never truncates. A grid-cols-4 cell easily fits every label at
// its normal width, so these apply unconditionally without visibly changing
// anything above the phone breakpoint -- they only matter once a column
// actually runs out of room.
const REPORT_TAB_LABEL_CLASSES =
  'min-w-0 overflow-hidden whitespace-nowrap max-[700px]:text-[0.75rem]';

const REPORT_ALERT_CLASSES =
  'cosci-report-alert mx-8 mt-4 rounded-xl border border-cosci-danger-border ' +
  'bg-cosci-danger-bg px-4 py-3 text-cosci-danger-fg';

const REPORT_TOAST_CLASSES =
  'reference-report-toast fixed right-4 bottom-4 z-50 rounded-xl border ' +
  'border-cosci-danger-border bg-cosci-danger-bg px-4 py-3 ' +
  'text-cosci-danger-fg';

const REPORT_SKELETON_CLASSES =
  'cosci-report-skeleton mx-auto my-9 grid w-[min(100%_-_3rem,58rem)] gap-4 ' +
  'max-[700px]:mt-5 max-[700px]:mb-12 ' +
  'max-[700px]:w-[min(100%_-_1.2rem,100%)] max-[700px]:max-w-none';

/**
 * Tab-switch side effects. The tabs themselves are links, so the route change
 * is the browser's (or the router's) job; what is left here is the special
 * case: bumping ideasViewKey when "All Ideas" is re-tapped while already
 * active, so IdeasTab remounts and resets its mobile master-detail selection
 * back to the list. This is a second, independent escape alongside the
 * titlebar's own Back arrow (see reportBackTarget below) — MobileIdeaView
 * itself still renders no back control of its own (see MobileIdeaView in
 * ideas_tab.tsx).
 */
export function useTabNavigation(id: string | undefined, activeTab: TabName) {
  // Bumped when "All Ideas" is re-tapped, remounting IdeasTab to reset its
  // mobile master-detail selection back to the list.
  const [ideasViewKey, setIdeasViewKey] = useState(0);

  const onTabChange = useCallback(
    (nextTab: TabName) => {
      if (!id) return;
      if (nextTab === 'ideas' && activeTab === 'ideas') {
        setIdeasViewKey(key => key + 1);
      }
    },
    [id, activeTab],
  );

  return {ideasViewKey, onTabChange};
}

// Where the titlebar's back control goes, and how it is labelled. An open
// idea (?idea= on the ideas tab) wins: on mobile that detail view has no
// back control of its own (see MobileIdeaView in ideas_tab.tsx), so this is
// its only escape back to the ranked list short of the browser's own back
// gesture. With no idea open, the control means one thing on every run --
// leave the run for the workspace. It used to divert to the conversation a
// run came from, which is now the shell header's session switch's job (see
// SessionSwitch): one arrow that changed destination depending on whether a
// chat happened to exist made "back" unpredictable, and left a run started
// outside a conversation with no way home at all.
function reportBackTarget(
  id: string | undefined,
  selectedIdeaId: string | null,
): {to: string; label: string} {
  if (id && selectedIdeaId) {
    return {to: tabPath(id, 'ideas'), label: 'Back to ranked ideas'};
  }
  return {to: '/', label: 'Back'};
}

/**
 * Titlebar: back link plus the run's (possibly domain-overridden) title.
 *
 * @param title The run's display title.
 * @param activeTab The currently active report tab, so the back control
 *   knows whether an `?idea=` param belongs to the ideas tab (and is thus a
 *   live detail selection) or is stale from a different tab.
 */
export function ReportTitlebar({
  title,
  activeTab,
}: {
  title: string;
  activeTab?: TabName;
}) {
  const {id} = useParams<{id: string}>();
  const [searchParams] = useSearchParams();
  const isMobile = useIsMobile();
  // Only the phone breakpoint replaces the ranked list with the detail, so
  // only there is the list somewhere the reader needs a way back to. The
  // desktop split-pane shows both at once and its Back control keeps
  // meaning "leave the run" -- retargeting it there would strand a reader
  // who pressed Back to get out.
  const selectedIdeaId =
    isMobile && activeTab === 'ideas' ? searchParams.get('idea') : null;
  const back = reportBackTarget(id, selectedIdeaId);
  return (
    <header className={REPORT_TITLEBAR_CLASSES}>
      <div className={REPORT_TITLE_LEFT_CLASSES}>
        <Link
          to={back.to}
          className={REPORT_BACK_CLASSES}
          aria-label={back.label}
        >
          <Icon aria-hidden="true" name="arrow_back" />
        </Link>
        <h1 className={REPORT_TITLE_CLASSES}>
          <TruncatedLabel className={REPORT_TITLE_TEXT_CLASSES} text={title} />
        </h1>
      </div>
    </header>
  );
}

/**
 * Tab nav: one link per TABS entry. Each tab is a real href, so a middle- or
 * cmd-click opens it in a new browser tab like any other link; onTabChange
 * still fires on a plain click for the ideas-remount side effect.
 *
 * This is deliberately a navigation landmark, not a tablist: the tabs are
 * real, deep-linkable URLs with working back/forward, so there is no
 * `role="tablist"`/`"tab"`/`"tabpanel"` triad, no `aria-selected`, and no
 * roving tabindex here -- each link is independently reachable by Tab like
 * any other link, and `aria-current="page"` (not `aria-selected`) marks the
 * active one, matching a nav rather than a widget. The content region below
 * carries its own accessible name instead of an `aria-controls` back to
 * this strip (see `reportSectionLabel`), since it is not this nav's
 * tabpanel. The app binds no keyboard shortcuts of its own, here or
 * anywhere else, so Tab and Enter are the whole keyboard story for this
 * strip.
 */
export function ReportTabNav({
  activeTab,
  onTabChange,
  tabs,
}: {
  activeTab: TabName;
  onTabChange: (tab: TabName) => void;
  // Which tabs this run has. Passed in rather than read from the
  // module-level TABS so the nav renders exactly what the run supports.
  tabs: readonly TabName[];
}) {
  // Read from the route rather than a prop so the nav's own signature (and
  // its call site) stays as it was.
  const {id} = useParams<{id: string}>();
  return (
    <nav className={REPORT_TABS_CLASSES} aria-label="Goal report sections">
      {tabs.map(tabName => (
        <Link
          key={tabName}
          to={tabPath(id ?? '', tabName)}
          className={reportTabButtonClass(tabName === activeTab)}
          aria-current={tabName === activeTab ? 'page' : undefined}
          aria-label={TAB_META[tabName].label}
          onClick={() => onTabChange(tabName)}
        >
          <Icon
            className={REPORT_TAB_ICON_CLASSES}
            aria-hidden="true"
            name={TAB_META[tabName].icon}
          />
          <TruncatedLabel
            className={`${REPORT_TAB_LABEL_CLASSES} max-[420px]:hidden`}
            text={TAB_META[tabName].label}
          />
          <span
            aria-hidden="true"
            className={`${REPORT_TAB_LABEL_CLASSES} min-[421px]:hidden`}
          >
            {TAB_META[tabName].short}
          </span>
        </Link>
      ))}
    </nav>
  );
}

// Picks the selected vs. unselected tab class variant.
function reportTabButtonClass(selected: boolean): string {
  return `${REPORT_TAB_BUTTON_BASE_CLASSES} ${
    selected ? REPORT_TAB_SELECTED_CLASSES : 'text-cosci-muted'
  }`;
}

/**
 * Inline error banner shown above the tab content; renders nothing when
 * there is no error.
 */
export function ReportErrorAlert({message}: {message: string | null}) {
  if (!message) return null;
  return (
    <div role="alert" className={REPORT_ALERT_CLASSES}>
      {message}
    </div>
  );
}

/** Fixed-position status toast, shown when a run ends failed/blocked. */
export function RunToast({message}: {message: string}) {
  return (
    <div role="status" className={REPORT_TOAST_CLASSES}>
      {message}
    </div>
  );
}

// Status and description for each non-completed terminal state.
const END_STATE_COPY: Record<
  TerminalNonCompletedStatus,
  {heading: string; description: string}
> = {
  failed: {
    heading: 'Run failed',
    description: 'This run failed before producing a goal report.',
  },
  cancelled: {
    heading: 'Run cancelled',
    description: 'This run was cancelled before producing a goal report.',
  },
  blocked: {
    heading: 'Run blocked',
    description: 'This run was blocked before producing a goal report.',
  },
};

// The recorded-error box: error-container tones for failed/blocked (the
// tones the design reserves for them), a neutral panel for cancelled.
const END_STATE_ERROR_CLASSES =
  'mt-8 rounded-md bg-th-destructive-container px-4 py-3 ' +
  'text-th-destructive-on-container';

const END_STATE_NEUTRAL_ERROR_CLASSES =
  'mt-8 rounded-md border border-cosci-border bg-cosci-panel px-4 py-3';

const FAILURE_GUIDANCE_CLASSES =
  'mt-6 rounded-md border border-cosci-border bg-cosci-panel px-4 py-3';

/**
 * Truthful end state for a run that terminated without completing: the
 * status and the run's recorded error, in place of report tabs whose
 * content either does not exist or would present a partial run as finished.
 */
export function RunEndState({
  status,
  error,
  failureKind,
}: {
  status: TerminalNonCompletedStatus;
  error: string | null;
  failureKind?: string | null;
}) {
  const copy = END_STATE_COPY[status];
  const guidance = status === 'failed' ? runFailureGuidance(failureKind) : null;
  return (
    <article className={REPORT_DOCUMENT_CLASSES}>
      <h2 className={REPORT_H2_CLASSES}>{copy.heading}</h2>
      <p>{copy.description}</p>
      {guidance && (
        <section
          aria-labelledby="run-failure-guidance-title"
          className={FAILURE_GUIDANCE_CLASSES}
        >
          <h3
            id="run-failure-guidance-title"
            className="m-0 text-sm font-medium"
          >
            Suggested next step
          </h3>
          <p className="mb-0 mt-2">{guidance.message}</p>
        </section>
      )}
      {error && (
        <div
          role="status"
          className={
            isCancelledStatus(status)
              ? END_STATE_NEUTRAL_ERROR_CLASSES
              : END_STATE_ERROR_CLASSES
          }
        >
          <strong>Recorded error</strong>
          <p className="mb-0 mt-2">{error}</p>
        </div>
      )}
    </article>
  );
}

const UNGROUNDED_NOTICE_CLASSES =
  'mx-auto mt-9 flex w-[min(100%_-_3rem,58rem)] items-start gap-3 rounded-md ' +
  'bg-th-warning-container px-4 py-3 text-th-on-warning-container ' +
  'max-[700px]:mt-5 max-[700px]:w-[min(100%_-_1.2rem,100%)] ' +
  'max-[700px]:max-w-none';

/**
 * Report-level notice for a completed run whose literature retrieval
 * returned nothing: the report below is not grounded in retrieved sources.
 */
export function ReportUngroundedNotice() {
  return (
    <div role="note" className={UNGROUNDED_NOTICE_CLASSES}>
      <Icon
        aria-hidden="true"
        name="warning"
        className="mt-[0.1rem] shrink-0 text-[1.25rem]"
      />
      <p className="m-0">
        No literature was retrieved for this run. The content below is not
        grounded in retrieved sources.
      </p>
    </div>
  );
}

const AWAITING_DECISION_NOTICE_CLASSES =
  'mx-auto mt-9 flex w-[min(100%_-_3rem,58rem)] items-start gap-3 ' +
  'rounded-md bg-th-warning-container px-4 py-3 ' +
  'text-th-on-warning-container max-[700px]:mt-5 ' +
  'max-[700px]:w-[min(100%_-_1.2rem,100%)] max-[700px]:max-w-none';

/**
 * Report-level notice that a paused run has one or more safety decisions
 * still awaiting a person -- shown above every tab's content (not folded
 * into the safety audit on Goal Details), because a run held at intake
 * produces no ideas, no overview, nothing to show on any other tab: without
 * this, the run just reads as empty rather than as waiting on a reviewer.
 * Sized and spaced like ReportUngroundedNotice, which it sits alongside
 * inside the same scrolling column (see RunDetailTabContent).
 */
export function AwaitingDecisionNotice({count}: {count: number}) {
  if (count <= 0) return null;
  const decisions = count === 1 ? 'decision' : 'decisions';
  return (
    <div role="note" className={AWAITING_DECISION_NOTICE_CLASSES}>
      <Icon
        aria-hidden="true"
        name="warning"
        className="mt-[0.1rem] shrink-0 text-[1.25rem]"
      />
      <p className="m-0">
        This run is paused, waiting on {count} safety {decisions} to be
        reviewed. Resolve {count === 1 ? 'it' : 'them'} on the Goal Details tab
        to let the run continue.
      </p>
    </div>
  );
}

/** Loading placeholder shown between mount and the first successful fetch. */
export function RunDetailSkeleton() {
  return (
    <div className={REPORT_SKELETON_CLASSES} aria-busy="true">
      <div className="wb-skeleton h-8 w-64" />
      <div className="wb-skeleton h-12 w-full" />
      <div className="wb-skeleton h-48 w-full" />
    </div>
  );
}
