// The Logs popover's summary chip row: the session size, the three level
// bands, and the number of distinct real runs behind them. Split out of
// layout_diagnostics.tsx to keep that module under the file-length
// ceiling; it is presentational only and owns no state.
import {type DiagnosticCounts} from './layout_diagnostics_data';

const CHIPS_ROW_CLASSES =
  'ucs-diagnostic-chips flex flex-wrap items-center gap-[0.45rem]';

const CHIP_CLASSES =
  'rounded-full bg-cosci-logs-accent-bg px-2 py-[0.15rem] ' +
  'text-[0.7rem] font-semibold whitespace-nowrap ' +
  'text-cosci-logs-accent-fg';

const ERROR_CHIP_CLASSES =
  'rounded-full bg-cosci-logs-danger-bg px-2 py-[0.15rem] ' +
  'text-[0.7rem] font-semibold whitespace-nowrap ' +
  'text-cosci-logs-danger-fg';

const WARN_CHIP_CLASSES =
  'rounded-full bg-cosci-logs-warn-bg px-2 py-[0.15rem] ' +
  'text-[0.7rem] font-semibold whitespace-nowrap ' +
  'text-cosci-logs-warn-fg';

// Separates the record tallies from the run count, which is not one of
// them (see below).
const DIVIDER_CLASSES = 'mx-[0.15rem] h-3 w-px bg-cosci-border';

/**
 * The record tallies, which are meant to be read as a sum.
 *
 * Every record shown carries exactly one level, so Errors + Warnings +
 * Info is the number of rows in the list. That identity is the whole
 * point of the row, and it only holds against the rows actually loaded:
 * `total` counts the session's entire filtered stream, of which the panel
 * fetches the newest hundred. Past that the bands stop summing to Total,
 * so a "Showing" chip appears and the bands are read against it instead
 * of silently disagreeing with the number beside them.
 */
function recordChips(
  total: number,
  shown: number,
  counts: DiagnosticCounts,
): [string, number, string][] {
  const toned = (count: number, tone: string) => (count ? tone : CHIP_CLASSES);
  return [
    ['Total', total, CHIP_CLASSES],
    ...(shown < total
      ? ([['Showing', shown, CHIP_CLASSES]] as [string, number, string][])
      : []),
    ['Errors', counts.errorCount, toned(counts.errorCount, ERROR_CHIP_CLASSES)],
    [
      'Warnings',
      counts.warningCount,
      toned(counts.warningCount, WARN_CHIP_CLASSES),
    ],
    ['Info', counts.infoCount, CHIP_CLASSES],
  ];
}

/**
 * Renders the popover's summary chips.
 *
 * The run count is deliberately set apart, after a divider and written as
 * a noun ("1 run"), because it counts runs and every chip before it
 * counts records. As a fifth "Runs 1" chip in the same ledger it read as
 * a fourth level band, and the row looked like it had failed to add up --
 * 38 + 2 + 1 against a total of 40.
 *
 * @param props.total Records added this browsing session.
 * @param props.shown Records currently loaded, which the bands tally.
 * @param props.counts Per-level tallies plus the distinct-run count.
 */
export function DiagnosticChips({
  total,
  shown,
  counts,
}: {
  total: number;
  shown: number;
  counts: DiagnosticCounts;
}) {
  return (
    <div className={CHIPS_ROW_CLASSES}>
      {recordChips(total, shown, counts).map(([label, count, className]) => (
        <span key={label} className={className}>
          {label} {count}
        </span>
      ))}
      <span aria-hidden="true" className={DIVIDER_CLASSES} />
      <span className={CHIP_CLASSES}>
        {counts.runCount} {counts.runCount === 1 ? 'run' : 'runs'}
      </span>
    </div>
  );
}
