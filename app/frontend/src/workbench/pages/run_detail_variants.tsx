import {useEffect, useMemo, useState} from 'react';
import {type CodeVariant, getCodeVariants} from '@/api/runs';
import {VariantsPlot} from '../components/tabs/variants_plot';
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
function scoreLabel(variant: CodeVariant): string {
  if (variant.fitness === null) return '—';
  const rounded = Math.round(variant.fitness * 1000) / 1000;
  return String(rounded);
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
}: {
  variant: CodeVariant;
  expanded: boolean;
  onToggle: () => void;
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
        </span>
        <span className="text-cosci-muted">{variant.status}</span>
        <span className="text-right tabular-nums">{scoreLabel(variant)}</span>
      </button>
      {expanded ? <VariantDetail variant={variant} /> : null}
    </>
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
export function VariantsView({variants}: {variants: CodeVariant[]}) {
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

  if (variants.length === 0) {
    return (
      <ReportDocument title="Variants">
        <section className={REPORT_SECTION_CLASSES}>
          <h3 className={REPORT_H3_CLASSES}>Variants</h3>
          <p>This run has not produced any variants yet.</p>
        </section>
      </ReportDocument>
    );
  }

  return (
    <ReportDocument title="Variants">
      <section className={REPORT_SECTION_CLASSES}>
        <h3 className={REPORT_H3_CLASSES}>Best score over time</h3>
        <VariantsPlot variants={variants} />
        <p className="text-sm text-cosci-muted">
          {best === null
            ? `${variants.length} attempts, none scored.`
            : `Best score ${scoreLabel(best)}, reached on attempt ${best.ordinal} of ${variants.length}.`}
        </p>
      </section>
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
  const [variants, setVariants] = useState<CodeVariant[] | null>(null);
  useEffect(() => {
    let live = true;
    getCodeVariants(runId)
      .then(rows => {
        if (live) setVariants(rows);
      })
      .catch(() => {
        // An older backend has no variants endpoint. An empty list is the
        // honest reading -- this run has no variants we can see -- and it
        // keeps the rest of the report readable during a rolling upgrade.
        if (live) setVariants([]);
      });
    return () => {
      live = false;
    };
  }, [runId]);
  if (variants === null) return null;
  return <VariantsView variants={variants} />;
}
