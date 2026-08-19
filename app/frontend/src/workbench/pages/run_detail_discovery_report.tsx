import {useEffect, useState} from 'react';
import {
  type DiscoveryReportPayload,
  type Report,
  fetchReportMarkdown,
} from '@/api/runs';
import {MarkdownMessage} from '@/components/markdown_message';
import {formatMeasured} from '@/lib/objectives';
import {ReportDocument} from './run_detail_document';

const STAT_GRID_CLASSES =
  'grid grid-cols-4 gap-3 max-[900px]:grid-cols-2 max-[520px]:grid-cols-1';

// Evenness below which the spread is called out rather than left to be
// read off a bare cell count. Mirrors the backend's threshold so the
// tile and the report's own prose never disagree.
const LOPSIDED_BELOW = 0.5;

// How much of the behaviour space the run reached, as one readable
// phrase. The count alone reads as thorough however lopsided the run
// was, so the evenness is spoken here rather than shown as a second
// number nobody knows how to weigh.
function spreadLabel(payload: DiscoveryReportPayload): string {
  if (!payload.niches_occupied) return '—';
  const count = String(payload.niches_occupied);
  return payload.niches_occupied > 1 && payload.niche_evenness < LOPSIDED_BELOW
    ? `${count}, uneven`
    : count;
}

function DiscoveryStats({payload}: {payload: DiscoveryReportPayload}) {
  const stats: [string, string][] = [
    ['Attempts', String(payload.variant_count)],
    ['Scored', String(payload.scored_count)],
    ['Approaches', spreadLabel(payload)],
    ['Best score', formatMeasured(payload.best_fitness, payload.objectives[0])],
  ];
  return (
    <dl className={STAT_GRID_CLASSES}>
      {stats.map(([label, value]) => (
        <div key={label} className="rounded-md bg-cosci-panel p-4">
          <dt className="text-sm text-cosci-muted">{label}</dt>
          <dd className="mt-1 text-2xl font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

// The report body opens with the goal as an H1, because report.md is
// also served on its own and a standalone document needs its title. The
// tab already prints that title above, so the heading is dropped here
// rather than removed from the Markdown -- printed twice it reads as a
// rendering fault.
function withoutLeadingTitle(markdown: string): string {
  return markdown.replace(/^#\s+.*(\r?\n)+/, '');
}

/**
 * Loads a run's report Markdown, or null while it is unavailable.
 *
 * Fetched rather than carried on the report row because the body holds
 * the winning program in full, which no list surface needs and every
 * list surface would otherwise pay for.
 *
 * @param runId Run whose report to load.
 * @returns The Markdown, or null until it arrives.
 */
function useReportMarkdown(runId: string | undefined): string | null {
  const [markdown, setMarkdown] = useState<string | null>(null);
  useEffect(() => {
    if (!runId) return;
    let live = true;
    void fetchReportMarkdown(runId)
      .then(text => {
        if (live) setMarkdown(text);
      })
      .catch(() => {
        // A missing body still leaves the stats above worth showing.
        if (live) setMarkdown(null);
      });
    return () => {
      live = false;
    };
  }, [runId]);
  return markdown;
}

/**
 * The Overview tab for a discovery run.
 *
 * Separate from the hypothesis overview rather than a branch inside it:
 * the two report payloads share no field, so one component reading both
 * would spend its length deciding which kind of run it is looking at.
 *
 * @param props The run's persisted report and its payload, already
 *   narrowed to the discovery shape.
 */
export function DiscoveryReportView({
  report,
  payload,
}: {
  report: Report;
  payload: DiscoveryReportPayload;
}) {
  const markdown = useReportMarkdown(report.run_id);
  return (
    <ReportDocument title={payload.research_goal}>
      <DiscoveryStats payload={payload} />
      {markdown && (
        <MarkdownMessage
          className="mt-8 text-sm"
          content={withoutLeadingTitle(markdown)}
        />
      )}
    </ReportDocument>
  );
}
