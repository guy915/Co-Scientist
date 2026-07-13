import {useCallback, useState} from 'react';
import {Link, useNavigate} from 'react-router-dom';
import {Icon, type IconName} from '@/components/icon';
import {reportMarkdownUrl} from '@/api/runs';
import {TruncatedLabel} from '../components/truncated_label';
import {TABS, type TabName} from '../run_tabs';
import {ReportShareControl} from './report_share_control';

// Material icon shown per tab in the nav bar (keyed by TabName so a missing
// entry is a compile error, not a silent blank icon).
const TAB_ICON_NAMES: Record<TabName, IconName> = {
  ideas: 'lightbulb',
  knowledge: 'menu_book',
  summary: 'summarize',
  specifications: 'assignment',
};

// Human-readable label shown per tab in the nav bar.
const TAB_LABELS: Record<TabName, string> = {
  ideas: 'Ideas',
  knowledge: 'Knowledge Base',
  summary: 'Summary',
  specifications: 'Run Specifications',
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

const REPORT_TAB_BUTTON_BASE_CLASSES =
  'relative grid min-w-0 cursor-pointer content-center justify-items-center ' +
  'gap-[0.35rem] border-0 bg-transparent font-[inherit] text-sm ' +
  'max-[720px]:gap-[0.2rem] max-[720px]:text-[0.68rem]';

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
 * Tab-switch handling: navigates to the new tab route, and (special case)
 * bumps ideasViewKey when "All Ideas" is re-tapped while already active so
 * IdeasTab remounts and resets its mobile master-detail selection back to
 * the list (that view has no back button of its own — see MobileIdeaView).
 */
export function useTabNavigation(id: string | undefined, activeTab: TabName) {
  const navigate = useNavigate();
  // Bumped when "All Ideas" is re-tapped, remounting IdeasTab to reset its
  // mobile master-detail selection back to the list.
  const [ideasViewKey, setIdeasViewKey] = useState(0);

  const onTabChange = useCallback(
    (nextTab: TabName) => {
      if (!id) return;
      if (nextTab === 'ideas' && activeTab === 'ideas') {
        setIdeasViewKey(key => key + 1);
      }
      // Always include the tab (details included) so every tab is the same
      // required-param route — switching tabs never remounts RunDetail.
      void navigate(`/runs/${id}/${nextTab}`);
    },
    [id, navigate, activeTab],
  );

  return {ideasViewKey, onTabChange};
}

/** Titlebar: back link plus the run's (possibly domain-overridden) title. */
export function ReportTitlebar({
  title,
  runId,
  onOpenAgent,
  shareEnabled,
  reportReady,
}: {
  title: string;
  runId: string;
  onOpenAgent: () => void;
  shareEnabled: boolean;
  reportReady: boolean;
}) {
  return (
    <header className={REPORT_TITLEBAR_CLASSES}>
      <div className={REPORT_TITLE_LEFT_CLASSES}>
        <Link to="/" className={REPORT_BACK_CLASSES} aria-label="Back">
          <Icon aria-hidden="true" name="arrow_back" />
        </Link>
        <h1 className={REPORT_TITLE_CLASSES}>
          <TruncatedLabel className={REPORT_TITLE_TEXT_CLASSES} text={title} />
        </h1>
      </div>
      <ReportActions
        runId={runId}
        onOpenAgent={onOpenAgent}
        shareEnabled={shareEnabled}
        reportReady={reportReady}
      />
    </header>
  );
}

function ReportActions({
  runId,
  onOpenAgent,
  shareEnabled,
  reportReady,
}: {
  runId: string;
  onOpenAgent: () => void;
  shareEnabled: boolean;
  reportReady: boolean;
}) {
  const actionClasses =
    'rounded-full border border-cosci-border px-3 py-2 text-xs no-underline text-cosci-fg hover:bg-cosci-hover';
  function openNotebookHandoff() {
    // The Markdown download is the interoperable handoff; NotebookLM itself
    // is proprietary and receives the file only if the scientist uploads it.
    const download = document.createElement('a');
    download.href = reportMarkdownUrl(runId);
    download.click();
    window.open('https://notebooklm.google.com/', '_blank', 'noopener');
  }
  return (
    <div className="flex shrink-0 items-center gap-2 max-[720px]:gap-1">
      <button type="button" className={actionClasses} onClick={onOpenAgent}>
        Open Agent
      </button>
      {reportReady && shareEnabled ? (
        <ReportShareControl runId={runId} className={actionClasses} />
      ) : null}
      {reportReady ? (
        <>
          <button
            type="button"
            className={`${actionClasses} max-[720px]:hidden`}
            onClick={openNotebookHandoff}
          >
            Open in NotebookLM
          </button>
          <a className={actionClasses} href={reportMarkdownUrl(runId)} download>
            Download
          </a>
        </>
      ) : null}
    </div>
  );
}

/** Tab nav: one button per TABS entry, routed via onTabChange. */
export function ReportTabNav({
  activeTab,
  onTabChange,
}: {
  activeTab: TabName;
  onTabChange: (tab: TabName) => void;
}) {
  return (
    <nav className={REPORT_TABS_CLASSES} aria-label="Goal report sections">
      {TABS.map(tabName => (
        <button
          key={tabName}
          type="button"
          className={reportTabButtonClass(tabName === activeTab)}
          aria-current={tabName === activeTab ? 'page' : undefined}
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
  );
}

// Picks the selected vs. unselected tab-button class variant.
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
