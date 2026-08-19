import {useEffect, useMemo, useState} from 'react';
import {
  type CodeVariant,
  type CodeVariantPage,
  type DiscoveryObjective,
  getCodeVariants,
} from '@/api/runs';
import {formatMeasured} from '@/lib/objectives';
import {VariantsPlot} from '../components/tabs/variants_plot';
import {VariantsTradeoff} from '../components/tabs/variants_tradeoff';
import {
  REPORT_H3_CLASSES,
  REPORT_SECTION_CLASSES,
  ReportDocument,
} from './run_detail_document';

const ROW_CLASSES =
  'grid grid-cols-[3rem_1fr_7rem_6rem] items-baseline gap-3 border-b ' +
  'border-cosci-border px-2 py-2 text-left text-sm';

const HEAD_CLASSES = `${ROW_CLASSES} text-cosci-muted`;

const CODE_CLASSES =
  'overflow-x-auto rounded bg-cosci-surface p-3 text-xs leading-[1.5]';

/**
 * How a variant's score reads in the table.
 *
 * An unscored variant shows a dash, never a zero. The two are different
 * facts -- no position in the ordering versus a real score of zero -- and
 * rendering them alike is how a table starts implying that a crashed
 * attempt was merely a bad one.
 */
function scoreLabel(
  variant: CodeVariant,
  objective?: DiscoveryObjective,
): string {
  return formatMeasured(variant.fitness, objective);
}

// Human-readable operator name. The seed has none, and saying so beats
// leaving the cell blank, which reads as missing data.
function operatorLabel(variant: CodeVariant): string {
  if (!variant.operator) return 'seed';
  return variant.operator.replace(/_/g, ' ');
}

function VariantDetail({variant}: {variant: CodeVariant}) {
  const files = Object.keys(variant.source).sort();
  return (
    <div className="border-b border-cosci-border px-2 py-4">
      {variant.rationale ? (
        <p className="mt-0 text-sm">{variant.rationale}</p>
      ) : null}
      {variant.artifacts?.stderr ? (
        <>
          <h4 className="mb-1 mt-3 text-sm font-medium">What went wrong</h4>
          <pre className={CODE_CLASSES}>{variant.artifacts.stderr}</pre>
        </>
      ) : null}
      {variant.diff ? (
        <>
          <h4 className="mb-1 mt-3 text-sm font-medium">The edit</h4>
          <pre className={CODE_CLASSES}>{variant.diff}</pre>
        </>
      ) : null}
      {files.map(path => (
        <div key={path}>
          <h4 className="mb-1 mt-3 text-sm font-medium">{path}</h4>
          <pre className={CODE_CLASSES}>{variant.source[path]}</pre>
        </div>
      ))}
    </div>
  );
}

function VariantRow({
  variant,
  expanded,
  onToggle,
  objective,
}: {
  variant: CodeVariant;
  expanded: boolean;
  onToggle: () => void;
  objective?: DiscoveryObjective;
}) {
  return (
    <>
      <button
        type="button"
        className={`${ROW_CLASSES} w-full cursor-pointer bg-transparent hover:bg-cosci-hover`}
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span className="text-cosci-muted">{variant.ordinal}</span>
        <span className="min-w-0 truncate">
          {operatorLabel(variant)}
          {variant.is_best_so_far ? (
            <span className="ml-2 text-xs text-cosci-accent">best so far</span>
          ) : null}
          {variant.is_pareto_optimal && !variant.is_best_so_far ? (
            // Only worth saying when it is not already flagged best:
            // with one objective the front *is* the best, and two
            // badges for one fact reads as two findings.
            <span className="ml-2 text-xs text-cosci-accent">
              best trade-off
            </span>
          ) : null}
        </span>
        <span className="text-cosci-muted">{variant.status}</span>
        <span className="text-right tabular-nums">
          {scoreLabel(variant, objective)}
        </span>
      </button>
      {expanded ? <VariantDetail variant={variant} /> : null}
    </>
  );
}

// How the run has gone, in one line: the best score and how much of the
// behaviour space it reached. The coverage half is what makes the
// diversity archive legible -- without it a reader sees a score creeping
// up and cannot tell whether the run explored or polished one idea.
function scoreSummary(
  variants: CodeVariant[],
  best: CodeVariant | null,
  objective?: DiscoveryObjective,
): string {
  if (best === null) return `${variants.length} attempts, none scored.`;
  const metric = objective?.metric ?? 'score';
  return (
    `Best ${metric} ${scoreLabel(best, objective)}, reached on attempt ` +
    `${best.ordinal} of ${variants.length}.`
  );
}

function coverageSummary(nichesOccupied: number): string {
  if (nichesOccupied === 0) return '';
  const noun = nichesOccupied === 1 ? 'approach' : 'approaches';
  return ` Explored ${nichesOccupied} distinct ${noun}.`;
}

function progressSummary(
  variants: CodeVariant[],
  best: CodeVariant | null,
  objectives: CodeVariantPage['objectives'],
  nichesOccupied: number,
): string {
  return (
    scoreSummary(variants, best, objectives[0]) +
    coverageSummary(nichesOccupied)
  );
}

// Says so when a run reached several cells but piled almost everything
// into one. Without it a high cell count reads as exploration, which is
// exactly the false reassurance the archive was built to remove.
function coverageCaveat(nichesOccupied: number, evenness: number): string {
  if (nichesOccupied < 2 || evenness >= 0.5) return '';
  return ' Most attempts landed in one of them.';
}

function TradeoffSection({
  variants,
  objectives,
}: {
  variants: CodeVariant[];
  objectives: CodeVariantPage['objectives'];
}) {
  if (objectives.length < 2) return null;
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>The trade-off</h3>
      <VariantsTradeoff variants={variants} objectives={objectives} />
      <p className="text-sm text-cosci-muted">
        This run optimizes {objectives.length} things at once, so there is no
        single best program. The highlighted attempts are the ones nothing beats
        on every objective — the real choices.
      </p>
    </section>
  );
}

function NoVariantsYet() {
  return (
    <ReportDocument title="Variants">
      <section className={REPORT_SECTION_CLASSES}>
        <h3 className={REPORT_H3_CLASSES}>Variants</h3>
        <p>This run has not produced any variants yet.</p>
      </section>
    </ReportDocument>
  );
}

/**
 * The "Variants" tab: how a discovery run's program changed over time.
 *
 * Every attempt is listed, including the ones that never ran. A list of
 * only the successes would answer "what worked" while making the search
 * itself invisible -- and the search, not any single program, is what the
 * run actually did.
 */
export function VariantsView({
  variants,
  objectives = [],
  nichesOccupied = 0,
  nicheEvenness = 0,
}: {
  variants: CodeVariant[];
  objectives?: CodeVariantPage['objectives'];
  nichesOccupied?: number;
  nicheEvenness?: number;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const best = useMemo(
    () =>
      variants.reduce<CodeVariant | null>(
        (winner, variant) =>
          variant.fitness !== null &&
          (winner === null || variant.fitness > (winner.fitness ?? -Infinity))
            ? variant
            : winner,
        null,
      ),
    [variants],
  );

  if (variants.length === 0) return <NoVariantsYet />;

  return (
    <ReportDocument title="Variants">
      <section className={REPORT_SECTION_CLASSES}>
        <h3 className={REPORT_H3_CLASSES}>Best score over time</h3>
        <VariantsPlot variants={variants} objective={objectives[0]} />
        <p className="text-sm text-cosci-muted">
          {progressSummary(variants, best, objectives, nichesOccupied) +
            coverageCaveat(nichesOccupied, nicheEvenness)}
        </p>
      </section>
      <TradeoffSection variants={variants} objectives={objectives} />
      <section className={REPORT_SECTION_CLASSES}>
        <h3 className={REPORT_H3_CLASSES}>Every attempt</h3>
        <div className={HEAD_CLASSES}>
          <span>#</span>
          <span>Change</span>
          <span>Outcome</span>
          <span className="text-right">Score</span>
        </div>
        {variants.map(variant => (
          <VariantRow
            key={variant.id}
            variant={variant}
            expanded={expandedId === variant.id}
            onToggle={() =>
              setExpandedId(expandedId === variant.id ? null : variant.id)
            }
            objective={objectives[0]}
          />
        ))}
      </section>
    </ReportDocument>
  );
}

/**
 * The Variants tab, fetching its own data.
 *
 * Kept out of the shared run-detail fetch on purpose: every other tab's
 * collections are fetched for every run, and variants exist on almost
 * none of them. Fetching here means the request happens exactly when a
 * discovery run's Variants tab is open, rather than on every report view
 * in the product.
 *
 * @param runId The run whose variants to show.
 */
export function VariantsSection({runId}: {runId: string}) {
  const [page, setPage] = useState<CodeVariantPage | null>(null);
  useEffect(() => {
    let live = true;
    getCodeVariants(runId)
      .then(loaded => {
        if (live) setPage(loaded);
      })
      .catch(() => {
        // An older backend has no variants endpoint. An empty page is the
        // honest reading -- this run has no variants we can see -- and it
        // keeps the rest of the report readable during a rolling upgrade.
        if (live) {
          setPage({
            variants: [],
            objectives: [],
            niches_occupied: 0,
            niche_evenness: 0,
          });
        }
      });
    return () => {
      live = false;
    };
  }, [runId]);
  if (page === null) return null;
  return (
    <VariantsView
      variants={page.variants}
      objectives={page.objectives}
      nichesOccupied={page.niches_occupied}
      nicheEvenness={page.niche_evenness}
    />
  );
}
