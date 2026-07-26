// The Logs popover's summary chip row: Total, the three level bands, and
// the number of distinct real runs in the loaded window. Split out of
// layout_diagnostics.tsx to keep that module under the file-length
// ceiling; it is presentational only and owns no state.
import {type DiagnosticCounts} from './layout_diagnostics_data';

const CHIPS_ROW_CLASSES = 'ucs-diagnostic-chips flex flex-wrap gap-[0.45rem]';

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

// [label, count, chip class] rows. The Errors and Warnings chips take
// their tone only when they are non-zero, so a quiet log reads as one calm
// row rather than a wall of alarm colors.
//
// Total is the size of the whole filtered stream this session (also the
// newest row's number), while the level chips tally only the loaded
// window — past 100 records they no longer sum to it.
function buildDiagnosticChips(
  total: number,
  counts: DiagnosticCounts,
): [string, number, string][] {
  const toned = (count: number, tone: string) => (count ? tone : CHIP_CLASSES);
  return [
    ['Total', total, CHIP_CLASSES],
    ['Errors', counts.errorCount, toned(counts.errorCount, ERROR_CHIP_CLASSES)],
    [
      'Warnings',
      counts.warningCount,
      toned(counts.warningCount, WARN_CHIP_CLASSES),
    ],
    ['Info', counts.infoCount, CHIP_CLASSES],
    ['Runs', counts.runCount, CHIP_CLASSES],
  ];
}

/**
 * Renders the popover's summary chips.
 *
 * @param props.total Records added this browsing session.
 * @param props.counts Per-level tallies over the loaded window.
 */
export function DiagnosticChips({
  total,
  counts,
}: {
  total: number;
  counts: DiagnosticCounts;
}) {
  return (
    <div className={CHIPS_ROW_CLASSES}>
      {buildDiagnosticChips(total, counts).map(([label, count, className]) => (
        <span key={label} className={className}>
          {label} {count}
        </span>
      ))}
    </div>
  );
}
