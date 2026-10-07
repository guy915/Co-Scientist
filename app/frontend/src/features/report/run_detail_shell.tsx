import {useCallback, useState, type ReactNode} from 'react';
import {Link, useParams, useSearchParams} from 'react-router-dom';
import {
  isCancelledStatus,
  type TerminalNonCompletedStatus,
} from '@/shared/api/runs';
import {Icon, type IconName} from '@/shared/ui/icon';
import {Card, TabNav, TabNavLink, Toast} from '@/shared/ui';
import {TruncatedLabel} from '@/shared/ui/truncated_label';
import {useIsMobile} from '@/shared/hooks/dom';
import {tabPath, type TabName} from '@/shared/lib/run_tabs';
import {runFailureGuidance} from './run_detail_data';
import {capitalizeTerm} from '@/shared/lib/text';
import {joinClasses} from '@/shared/ui/classes';

const TAB_META: Record<
  TabName,
  {icon: IconName; label: string; short: string}
> = {
  details: {icon: 'assignment', label: 'Goal Details', short: 'Details'},
  learning: {icon: 'menu_book', label: 'Learning', short: 'Learning'},
  overview: {icon: 'summarize', label: 'Research Overview', short: 'Overview'},
  ideas: {icon: 'lightbulb', label: 'All Ideas', short: 'Ideas'},
};

// Name content regions independently: deep-linked navigation is not an ARIA
// tab widget.
export function reportSectionLabel(tab: TabName): string {
  return TAB_META[tab].label;
}

// Retapping Ideas resets mobile detail to the list because that detail has no
// back control of its own.
export function useTabNavigation(id: string | undefined, activeTab: TabName) {
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

// On mobile, open-idea Back returns to the list; otherwise Back leaves the run
// for the workspace.
function reportBackTarget(
  id: string | undefined,
  selectedIdeaId: string | null,
): {to: string; label: string} {
  if (id && selectedIdeaId) {
    return {to: tabPath(id, 'ideas'), label: 'Back to ranked ideas'};
  }
  return {to: '/', label: 'Back'};
}

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
  // Desktop shows list and detail together, so Back must still leave the run.
  const selectedIdeaId =
    isMobile && activeTab === 'ideas' ? searchParams.get('idea') : null;
  const back = reportBackTarget(id, selectedIdeaId);
  return (
    <header className="cosci-report-titlebar flex min-w-0 items-center justify-between gap-6 border-b border-cosci-border px-9 max-[700px]:gap-[0.35rem] max-[700px]:px-[0.7rem]">
      <div className="cosci-report-title-left flex min-w-0 items-center gap-4 max-[700px]:gap-[0.45rem]">
        <Link
          to={back.to}
          className="cosci-report-back grid h-10 w-10 shrink-0 place-items-center rounded-full text-cosci-muted no-underline hover:bg-cosci-hover"
          aria-label={back.label}
        >
          <Icon aria-hidden="true" name="arrow_back" />
        </Link>
        <h1 className="m-0 min-w-0 overflow-hidden text-[1.2rem] leading-[1.25] font-normal tracking-normal max-[700px]:text-[0.9rem]">
          <TruncatedLabel
            className="block min-w-0 overflow-hidden whitespace-nowrap"
            text={title}
          />
        </h1>
      </div>
    </header>
  );
}

// Use navigation landmarks and ordinary links for deep URLs, browser history
// and keyboard semantics.
export function ReportTabNav({
  activeTab,
  onTabChange,
  tabs,
}: {
  activeTab: TabName;
  onTabChange: (tab: TabName) => void;
  tabs: readonly TabName[];
}) {
  const {id} = useParams<{id: string}>();
  return (
    <TabNav
      label="Goal report sections"
      variant="underline"
      current={activeTab}
      layoutClassName="reference-report-tabs grid-cols-4 max-[700px]:min-w-0 max-[700px]:overflow-x-hidden"
    >
      {tabs.map(tabName => (
        <TabNavLink
          key={tabName}
          variant="underline"
          to={tabPath(id ?? '', tabName)}
          current={tabName === activeTab}
          // Keeps the hover and focus state layer (index.css).
          className="reference-report-tab max-[700px]:gap-[0.2rem] max-[700px]:text-[0.68rem]"
          aria-label={TAB_META[tabName].label}
          onClick={() => onTabChange(tabName)}
        >
          <Icon
            className="text-[1.35rem] max-[700px]:text-[1.12rem] [@media(max-height:500px)]:hidden"
            aria-hidden="true"
            name={TAB_META[tabName].icon}
          />
          <TruncatedLabel
            // Constrain width and overflow for TruncatedLabel; otherwise there is no axis
            // against which to measure.
            className={
              'min-w-0 overflow-hidden whitespace-nowrap max-[700px]:text-[0.75rem] max-[420px]:hidden'
            }
            text={TAB_META[tabName].label}
          />
          <span
            aria-hidden="true"
            className={
              'min-w-0 overflow-hidden whitespace-nowrap max-[700px]:text-[0.75rem] min-[421px]:hidden'
            }
          >
            {TAB_META[tabName].short}
          </span>
        </TabNavLink>
      ))}
    </TabNav>
  );
}

export function ReportErrorAlert({message}: {message: string | null}) {
  if (!message) return null;
  return (
    <Card
      role="alert"
      tone="danger"
      layoutClassName="cosci-report-alert ui-motion-enter mx-8 mt-4"
    >
      {message}
    </Card>
  );
}

export function RunToast({message}: {message: string | null}) {
  return (
    <Toast tone="danger" placement="end">
      {message}
    </Toast>
  );
}

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

// Failed, blocked and cancelled runs must not present partial output as a
// completed report.
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
    <article
      className={joinClasses(REPORT_DOCUMENT_CLASSES, 'ui-motion-enter')}
    >
      <h2 className={REPORT_H2_CLASSES}>{copy.heading}</h2>
      <p>{copy.description}</p>
      {guidance && (
        <Card
          as="section"
          aria-labelledby="run-failure-guidance-title"
          outlined
          layoutClassName="mt-6"
        >
          <h3
            id="run-failure-guidance-title"
            className="m-0 text-sm font-medium"
          >
            Suggested next step
          </h3>
          <p className="mb-0 mt-2">{guidance.message}</p>
        </Card>
      )}
      {error && (
        <Card
          role="status"
          tone={isCancelledStatus(status) ? 'neutral' : 'danger'}
          outlined
          layoutClassName="mt-8"
        >
          <strong>Recorded error</strong>
          <p className="mb-0 mt-2">{error}</p>
        </Card>
      )}
    </article>
  );
}

const NOTICE_LAYOUT_CLASSES =
  'ui-motion-enter mx-auto mt-9 flex w-[min(100%_-_3rem,58rem)] items-start gap-3 max-[700px]:mt-5 max-[700px]:w-[min(100%_-_1.2rem,100%)] max-[700px]:max-w-none';

// A completed run without literature still needs an explicit ungrounded report
// notice.
export function ReportUngroundedNotice() {
  return (
    <Card role="note" tone="warning" layoutClassName={NOTICE_LAYOUT_CLASSES}>
      <Icon
        aria-hidden="true"
        name="warning"
        className="mt-[0.1rem] shrink-0 text-[1.25rem]"
      />
      <p className="m-0">
        No literature was retrieved for this run. The content below is not
        grounded in retrieved sources.
      </p>
    </Card>
  );
}

// Show pending safety review above every tab; intake holds can otherwise look
// like an empty run.
export function AwaitingDecisionNotice({count}: {count: number}) {
  if (count <= 0) return null;
  const decisions = count === 1 ? 'decision' : 'decisions';
  return (
    <Card role="note" tone="warning" layoutClassName={NOTICE_LAYOUT_CLASSES}>
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
    </Card>
  );
}

export function RunDetailSkeleton() {
  return (
    <div
      className="cosci-report-skeleton mx-auto my-9 grid w-[min(100%_-_3rem,58rem)] gap-4 max-[700px]:mt-5 max-[700px]:mb-12 max-[700px]:w-[min(100%_-_1.2rem,100%)] max-[700px]:max-w-none"
      aria-busy="true"
    >
      <div className="rounded-md bg-(--cosci-icon-button-hover-bg) h-8 w-64" />
      <div className="rounded-md bg-(--cosci-icon-button-hover-bg) h-12 w-full" />
      <div className="rounded-md bg-(--cosci-icon-button-hover-bg) h-48 w-full" />
    </div>
  );
}

export const REPORT_DOCUMENT_CLASSES =
  'cosci-report-document mx-auto mt-9 mb-24 w-[min(100%_-_3rem,58rem)] ' +
  'text-base leading-[1.5] max-[700px]:mt-5 max-[700px]:mb-12 ' +
  'max-[700px]:w-[min(100%_-_1.2rem,100%)] max-[700px]:max-w-none';

export const REPORT_H2_CLASSES =
  'font-gsans mt-9 mb-6 text-[2rem] leading-10 font-normal tracking-normal ' +
  'max-[700px]:mt-6 max-[700px]:mb-4 ' +
  'max-[700px]:text-[clamp(1.5rem,6.8vw,2rem)] max-[700px]:leading-[1.2]';

export const REPORT_H3_CLASSES =
  'font-gsans mt-[1.4rem] mb-3 text-[1.75rem] leading-9 font-normal ' +
  'max-[700px]:text-[clamp(1.35rem,6.5vw,1.75rem)] max-[700px]:leading-[1.2]';

export const REPORT_H4_CLASSES = 'mt-4 mb-[0.35rem] text-base font-medium';

export const REPORT_LIST_CLASSES = 'mt-[0.45rem] mb-0 pl-[1.35rem]';

export const REPORT_SECTION_CLASSES = 'cosci-overview-section mt-8';

export function ReportDocument({
  title,
  children,
  className,
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <article className={joinClasses(REPORT_DOCUMENT_CLASSES, className)}>
      <h2 className={REPORT_H2_CLASSES}>{title}</h2>
      {children}
    </article>
  );
}

export function ReportList({title, values}: {title: string; values: string[]}) {
  if (!values.length) return null;
  return (
    <section className="cosci-report-list">
      <h4 className={REPORT_H4_CLASSES}>{title}:</h4>
      <ul className={REPORT_LIST_CLASSES}>
        {values.map(value => (
          <li key={value}>{capitalizeTerm(value)}</li>
        ))}
      </ul>
    </section>
  );
}
