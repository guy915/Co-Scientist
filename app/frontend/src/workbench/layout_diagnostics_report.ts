import {useState} from 'react';
import {reportAppLogs} from '@/api/logs';
import {useResetTimer} from './hooks/use_reset_timer';
import type {
  DiagnosticCounts,
  DiagnosticLogEntry,
} from './layout_diagnostics_data';
import {
  browserExportContext,
  formatDiagnosticExport,
} from './layout_diagnostics_export';

/** Where one report attempt has got to. */
export type ReportStatus = 'idle' | 'sending' | 'sent' | 'failed';

// How long the button holds its outcome before offering "Report" again.
// Longer than the Copy button's window because a failure has to be readable,
// not just noticed.
const OUTCOME_RESET_MS = 4_000;

/** What the button reads in each state. */
const REPORT_LABELS: Record<ReportStatus, string> = {
  idle: 'Report',
  sending: 'Sending…',
  sent: 'Sent',
  failed: "Couldn't send",
};

/** The button's label for a status. */
export function reportLabel(status: ReportStatus): string {
  return REPORT_LABELS[status];
}

/** The log window a report covers, as the panel is currently showing it. */
export interface ReportSubject {
  entries: DiagnosticLogEntry[];
  total: number;
  counts: DiagnosticCounts;
}

/**
 * Sends the panel's current view to the operator and reports how it went.
 *
 * The outcome is held on the button rather than announced in a toast: the
 * click happens inside the popover and the answer belongs next to it. A
 * failure is shown, never swallowed — a report that silently did not arrive
 * is worse than no button at all, since the scientist stops looking for
 * another way to tell anyone.
 */
export function useLogReport() {
  const [status, setStatus] = useState<ReportStatus>('idle');
  const timer = useResetTimer();

  function settle(outcome: ReportStatus) {
    setStatus(outcome);
    timer.schedule(() => setStatus('idle'), OUTCOME_RESET_MS);
  }

  async function send(subject: ReportSubject) {
    // A second click while the first is in flight would mail the same
    // window twice, which is the one thing the rate limit is there to
    // catch; catching it here keeps that budget for real reports.
    if (status === 'sending') return;
    // 'sending' is not a transient label, so any pending expiry from a
    // previous attempt is dropped rather than left to clear it.
    timer.cancel();
    setStatus('sending');
    try {
      await reportAppLogs(
        formatDiagnosticExport({...subject, context: browserExportContext()}),
      );
      settle('sent');
    } catch {
      settle('failed');
    }
  }

  return {status, send};
}
