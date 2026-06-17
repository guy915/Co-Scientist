import '@material/web/icon/icon.js';
import '@material/web/button/filled-button.js';
import '@material/web/button/outlined-button.js';
import {useEffect, useState} from 'react';
import ReactMarkdown from 'react-markdown';
import type {Report, SafetyDecision} from '@/api/runs';
import {reportMarkdownUrl} from '@/api/runs';
import {useT} from '@/i18n';

/**
 * Renders the synthesized report markdown with export and print actions.
 *
 * @param props The run id, its report, and the run's safety decisions.
 */
export function ReportTab({
  runId,
  report,
  safety,
}: {
  runId: string;
  report: Report | null;
  safety: SafetyDecision[];
}) {
  const t = useT();
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const finalSafety = safety.find(s => s.stage === 'final');

  useEffect(() => {
    if (!report) return;
    setLoading(true);
    void fetch(reportMarkdownUrl(runId))
      .then(res => (res.ok ? res.text() : null))
      .then(text => setMarkdown(text))
      .finally(() => setLoading(false));
  }, [report, runId]);

  async function copyMarkdown() {
    if (!markdown) return;
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore — clipboard may be unavailable in non-secure contexts */
    }
  }

  if (!report) {
    return (
      <div
        className="rounded border p-6 text-sm text-center"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          color: 'var(--md-sys-color-on-surface-variant)',
        }}
      >
        {t('report.empty')}
      </div>
    );
  }

  return (
    <div className="flex flex-col-reverse gap-4 lg:grid lg:grid-cols-4">
      <article
        className="lg:col-span-3 rounded border p-4 sm:p-6 wb-fade-in"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          backgroundColor: 'var(--md-sys-color-surface-container-low)',
        }}
      >
        {loading && (
          <div className="space-y-2" aria-busy="true">
            <div className="wb-skeleton h-6 w-2/3" />
            <div className="wb-skeleton h-4 w-full" />
            <div className="wb-skeleton h-4 w-5/6" />
            <div className="wb-skeleton h-4 w-4/6" />
          </div>
        )}
        {markdown && (
          <div className="wb-markdown">
            <ReactMarkdown>{markdown}</ReactMarkdown>
          </div>
        )}
      </article>
      <aside className="grid grid-cols-2 gap-2 sm:gap-3 lg:flex lg:flex-col wb-print-hide">
        <md-filled-button
          onclick={
            (() => {
              const a = document.createElement('a');
              a.href = reportMarkdownUrl(runId);
              a.download = 'report.md';
              a.click();
            }) as EventListener
          }
        >
          <md-icon slot="icon" aria-hidden="true">
            download
          </md-icon>
          {t('report.downloadMarkdown')}
        </md-filled-button>
        <md-outlined-button
          onclick={
            (() => {
              const a = document.createElement('a');
              a.href = `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(report.payload, null, 2))}`;
              a.download = `${runId}.json`;
              a.click();
            }) as EventListener
          }
        >
          <md-icon slot="icon" aria-hidden="true">
            description
          </md-icon>
          {t('report.downloadJson')}
        </md-outlined-button>
        <md-outlined-button
          onclick={(() => void copyMarkdown()) as EventListener}
          disabled={!markdown || undefined}
        >
          <md-icon slot="icon" aria-hidden="true">
            {copied ? 'check' : 'content_copy'}
          </md-icon>
          {copied ? t('action.copied') : t('report.copyMarkdown')}
        </md-outlined-button>
        <md-outlined-button onclick={(() => window.print()) as EventListener}>
          <md-icon slot="icon" aria-hidden="true">
            print
          </md-icon>
          {t('action.print')}
        </md-outlined-button>
        {finalSafety && finalSafety.decision !== 'allow' && (
          <div
            className="col-span-2 rounded border p-3 text-xs lg:col-span-1"
            style={{
              borderColor: 'var(--color-th-warning)',
              backgroundColor:
                'color-mix(in srgb, var(--color-th-warning) 12%, transparent)',
            }}
          >
            <div className="flex items-center gap-1.5 font-medium mb-1">
              <md-icon style={{fontSize: '14px'}} aria-hidden="true">
                warning
              </md-icon>
              {t('report.finalSafety', {decision: finalSafety.decision})}
            </div>
            <div style={{color: 'var(--md-sys-color-on-surface-variant)'}}>
              {finalSafety.reason}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
