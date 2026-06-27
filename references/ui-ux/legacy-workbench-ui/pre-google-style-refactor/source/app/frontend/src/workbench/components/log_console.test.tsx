import {describe, it, expect} from 'vitest';
import type {LogEntry} from '../log_context';
import {formatDiagnosticLog} from './log_console';

function makeEntry(seq: number, type = 'lifecycle'): LogEntry {
  return {
    run_id: 'run-1',
    run_label: 'Test run',
    seq,
    type,
    payload: {step: seq},
    created_at: 1_719_000_000 + seq,
  };
}

describe('formatDiagnosticLog', () => {
  it('includes explanatory sections and statistics', () => {
    const text = formatDiagnosticLog(
      [
        makeEntry(1),
        {...makeEntry(2, 'status'), payload: {status: 'failed', error: 'x'}},
        {...makeEntry(3, 'report'), payload: {report_id: 7}},
      ],
      {
        currentUrl: 'http://localhost:5173/runs',
        userAgent: 'Vitest',
        exportedAt: new Date('2026-06-19T01:00:00Z'),
      },
    );

    expect(text).toContain('=== ABOUT THESE DIAGNOSTIC LOGS ===');
    expect(text).toContain('=== WHAT THIS TOOL TRACKS ===');
    expect(text).toContain('Current URL: http://localhost:5173/runs');
    expect(text).toContain('Browser: Vitest');
    expect(text).toContain('Total Logs: 3');
    expect(text).toContain('Errors: 1');
    expect(text).toContain('Success: 1');
    expect(text).toContain('Info: 1');
    expect(text).toContain('#2 ');
    expect(text).toContain('ERROR: [Test run] STATUS');
  });

  it('does not truncate long logs when formatting for copy', () => {
    const entries = Array.from({length: 130}, (_, i) => makeEntry(i + 1));

    const text = formatDiagnosticLog(entries);

    expect(text).toContain('Total Logs: 130');
    expect(text).toContain('#130 ');
    expect(text).toContain('"step": 130');
  });
});
