import {useCallback, useState} from 'react';
import {Link, useParams} from 'react-router-dom';
import {type RunStatus} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {TruncatedLabel} from '../components/truncated_label';
import {TABS, tabPath, type TabName} from '../run_tabs';
import {
  REPORT_DOCUMENT_CLASSES,
  REPORT_H2_CLASSES,
} from './run_detail_document';

// Icon and label shown per tab in the nav bar (keyed by TabName so a missing
// entry is a compile error, not a silent blank tab).
const TAB_META: Record<TabName, {icon: IconName; label: string}> = {
  details: {icon: 'assignment', label: 'Goal Details'},
  learning: {icon: 'menu_book', label: 'Learning'},
  overview: {icon: 'summarize', label: 'Research Overview'},
  ideas: {icon: 'lightbulb', label: 'All Ideas'},
};

const REPORT_TITLEBAR_CLASSES =
  'cosci-report-titlebar flex min-w-0 items-center justify-between gap-6 ' +
  'border-b border-cosci-border px-9 max-[720px]:gap-[0.35rem] ' +
  'max-[720px]:px-[0.7rem]';

const REPORT_TITLE_LEFT_CLASSES =
  'cosci-report-title-left flex min-w-0 items-center gap-4 ' +
  'max-[720px]:gap-[0.45rem]';

const REPORT_BACK_CLASSES =
  'cosci-report-back grid h-10 w-10 shrink-0 ' +
  'place-items-center rounded-full text-cosci-muted ' +
  'no-underline hover:bg-cosci-hover';

const REPORT_TITLE_CLASSES =
  'm-0 min-w-0 overflow-hidden text-[1.2rem] leading-[1.25] ' +
  'font-normal tracking-normal max-[720px]:text-[0.9rem]';

const REPORT_TITLE_TEXT_CLASSES =
  'block min-w-0 overflow-hidden whitespace-nowrap';

const REPORT_TABS_CLASSES =
  'reference-report-tabs grid grid-cols-4 border-b border-cosci-border ' +
  'max-[720px]:min-w-0 max-[720px]:overflow-x-hidden';

// The tabs are anchors (so a middle/cmd-click opens the tab in a new browser
// tab), hence the explicit no-underline: everything else here matches the
// buttons they replaced. `reference-report-tab` is the hook the hover/focus
// state layer in index.css keys on -- it must stay on whatever element the
// tab is rendered as.
const REPORT_TAB_BUTTON_BASE_CLASSES =
  'reference-report-tab relative grid min-w-0 cursor-pointer content-center ' +
  'justify-items-center gap-[0.35rem] border-0 bg-transparent ' +
  'font-[inherit] text-sm no-underline max-[720px]:gap-[0.2rem] ' +
  'max-[720px]:text-[0.68rem]';

const REPORT_TAB_SELECTED_CLASSES =
  'text-cosci-blue after:absolute after:right-[1.1rem] after:bottom-0 ' +
  'after:left-[1.1rem] after:h-[0.18rem] after:rounded-t-full ' +
  "after:bg-cosci-blue-strong after:content-['']";

const REPORT_TAB_ICON_CLASSES = 'text-[1.35rem] max-[720px]:text-[1.12rem]';

const REPORT_TAB_LABEL_CLASSES = 'max-[720px]:text-[0.75rem]';

const REPORT_ALERT_CLASSES =
  'cosci-report-alert mx-8 mt-4 rounded-xl border border-cosci-danger-border ' +
  'bg-cosci-danger-bg px-4 py-3 text-cosci-danger-fg';

const REPORT_TOAST_CLASSES =
  'reference-report-toast fixed right-4 bottom-4 z-50 rounded-xl border ' +
  'border-cosci-danger-border bg-cosci-danger-bg px-4 py-3 ' +
  'text-cosci-danger-fg';

const REPORT_SKELETON_CLASSES =
  'cosci-report-skeleton mx-auto my-9 grid w-[min(100%_-_3rem,58rem)] gap-4 ' +
  'max-[720px]:mt-5 max-[720px]:mb-12 ' +
  'max-[720px]:w-[min(100%_-_1.2rem,100%)] max-[720px]:max-w-none';

/**
 * Tab-switch side effects. The tabs themselves are links, so the route change
 * is the browser's (or the router's) job; what is left here is the special
 * case: bumping ideasViewKey when "All Ideas" is re-tapped while already
 * active, so IdeasTab remounts and resets its mobile master-detail selection
 * back to the list (that view has no back button of its own — see
 * MobileIdeaView).
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

/**
 * Titlebar: back link plus the run's (possibly domain-overridden) title.
 *
 * @param title The run's display title.
 * @param chatId The conversation this run was started from, when the rail
 *   knows of one. The rail sends such a session straight to its run, so
 *   this arrow is what keeps the transcript reachable; without a chat it
 *   falls back to the workspace, as it always did.
 */
export function ReportTitlebar({
  title,
  chatId,
}: {
  title: string;
  chatId?: string;
}) {
  return (
    <header className={REPORT_TITLEBAR_CLASSES}>
      <div className={REPORT_TITLE_LEFT_CLASSES}>
        <Link
          to={chatId ? `/chats/${chatId}` : '/'}
          className={REPORT_BACK_CLASSES}
          aria-label={chatId ? 'Back to conversation' : 'Back'}
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
 */
export function ReportTabNav({
  activeTab,
  onTabChange,
}: {
  activeTab: TabName;
  onTabChange: (tab: TabName) => void;
}) {
  // Read from the route rather than a prop so the nav's own signature (and
  // its call site) stays as it was.
  const {id} = useParams<{id: string}>();
  return (
    <nav className={REPORT_TABS_CLASSES} aria-label="Goal report sections">
      {TABS.map(tabName => (
        <Link
          key={tabName}
          to={tabPath(id ?? '', tabName)}
          className={reportTabButtonClass(tabName === activeTab)}
          aria-current={tabName === activeTab ? 'page' : undefined}
          onClick={() => onTabChange(tabName)}
        >
          <Icon
            className={REPORT_TAB_ICON_CLASSES}
            aria-hidden="true"
            name={TAB_META[tabName].icon}
          />
          <span className={REPORT_TAB_LABEL_CLASSES}>
            {TAB_META[tabName].label}
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

/** Terminal run statuses that ended without a completed goal report. */
export type TerminalNonCompletedStatus = 'failed' | 'cancelled' | 'blocked';

const TERMINAL_NON_COMPLETED_STATUSES: readonly RunStatus[] = [
  'failed',
  'cancelled',
  'blocked',
];

/**
 * Whether a run status is terminal but not `completed` — a run that ended
 * without producing a report.
 *
 * @param status The run status (may be undefined before load).
 * @returns True when the run ended failed, cancelled, or blocked.
 */
export function isTerminalNonCompletedStatus(
  status: RunStatus | undefined,
): status is TerminalNonCompletedStatus {
  return Boolean(status && TERMINAL_NON_COMPLETED_STATUSES.includes(status));
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

/**
 * Truthful end state for a run that terminated without completing: the
 * status and the run's recorded error, in place of report tabs whose
 * content either does not exist or would present a partial run as finished.
 */
export function RunEndState({
  status,
  error,
}: {
  status: TerminalNonCompletedStatus;
  error: string | null;
}) {
  const copy = END_STATE_COPY[status];
  return (
    <article className={REPORT_DOCUMENT_CLASSES}>
      <h2 className={REPORT_H2_CLASSES}>{copy.heading}</h2>
      <p>{copy.description}</p>
      {error && (
        <div
          role="status"
          className={
            status === 'cancelled'
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
  'max-[720px]:mt-5 max-[720px]:w-[min(100%_-_1.2rem,100%)] ' +
  'max-[720px]:max-w-none';

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
