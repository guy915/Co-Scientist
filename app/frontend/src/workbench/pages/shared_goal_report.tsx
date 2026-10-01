import {type ReactNode, useEffect, useState} from 'react';
import {useParams} from 'react-router-dom';
import {
  getSharedGoalReport,
  type SharedGoalReport,
  type SharedRun,
} from '@/api/runs';

const PAGE_CLASSES =
  'mx-auto mb-24 grid w-[min(60rem,calc(100%-2rem))] gap-10 py-10 ' +
  'text-cosci-fg';

// Loads the shared report for a token, tracking load errors.
function useSharedReport(token: string) {
  const [shared, setShared] = useState<SharedGoalReport | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let current = true;
    void getSharedGoalReport(token)
      .then(value => {
        if (current) setShared(value);
      })
      .catch(caught => {
        if (current) {
          setError(
            caught instanceof Error ? caught.message : 'Share unavailable',
          );
        }
      });
    return () => {
      current = false;
    };
  }, [token]);
  return {shared, error};
}

// The report headline: the model-generated title, else the raw goal.
function reportHeadline(run: SharedRun): string {
  return run.title || run.research_goal;
}

// The Run Specifications label for the run's mode.
function runTypeLabel(run: SharedRun): string {
  return run.run_mode === 'advanced' ? 'Advanced Run' : 'Standard Run';
}

/** Read-only public Goal Report rendered exclusively through a share token. */
export function SharedGoalReportPage() {
  const {token = ''} = useParams<{token: string}>();
  const {shared, error} = useSharedReport(token);

  if (error)
    return (
      <main role="alert" className={PAGE_CLASSES}>
        This shared Goal Report is unavailable.
      </main>
    );
  if (!shared)
    return (
      <main aria-busy="true" className={PAGE_CLASSES}>
        Loading shared Goal Report…
      </main>
    );
  const {run} = shared;
  return (
    <main className={PAGE_CLASSES}>
      <header>
        <p className="text-sm text-cosci-muted">Public Goal Report</p>
        <h1 className="mt-2 text-3xl">{reportHeadline(run)}</h1>
        <p className="mt-3">{run.research_goal}</p>
      </header>
      <SharedReportSections shared={shared} />
      <ReportSection title="Run Specifications">
        <p>
          <strong>Research Challenge:</strong> {run.research_goal}
        </p>
        <p>
          <strong>Run type:</strong> {runTypeLabel(run)}
        </p>
      </ReportSection>
    </main>
  );
}

// The report's content sections: ideas, knowledge base, and summary.
function SharedReportSections({shared}: {shared: SharedGoalReport}) {
  const {report, hypotheses, evidence} = shared;
  const insights = report.payload.agent_insights;
  return (
    <>
      <ReportSection title="Ideas">
        <ol className="grid gap-3">
          {hypotheses.map(hypothesis => (
            <li key={hypothesis.id}>
              <strong>{hypothesis.title}</strong> · Elo {hypothesis.elo_rating}
              <p>{hypothesis.statement}</p>
            </li>
          ))}
        </ol>
      </ReportSection>
      <ReportSection title="Knowledge Base">
        {(report.payload.knowledge_base || []).map(topic => (
          <article key={topic.id} className="mb-4">
            <h3 className="text-lg font-medium">{topic.title}</h3>
            <p>{topic.summary}</p>
          </article>
        ))}
        <p className="text-sm text-cosci-muted">
          {evidence.length} references analysed
        </p>
      </ReportSection>
      <ReportSection title="Summary">
        <h3 className="text-lg font-medium">Agent Insights</h3>
        <ul className="mt-2 list-disc pl-5">
          {(insights?.key_findings || []).map(finding => (
            <li key={finding}>{finding}</li>
          ))}
        </ul>
      </ReportSection>
    </>
  );
}

function ReportSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section>
      <h2 className="mb-4 border-b border-cosci-border pb-2 text-2xl">
        {title}
      </h2>
      {children}
    </section>
  );
}
