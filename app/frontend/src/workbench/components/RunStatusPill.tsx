import type {RunStatus} from '@/api/runs';
import {useT} from '@/i18n';

const STYLES: Record<RunStatus, {bg: string; fg: string; labelKey: string}> = {
  draft: {
    bg: 'var(--md-sys-color-surface-variant)',
    fg: 'var(--md-sys-color-on-surface-variant)',
    labelKey: 'status.draft',
  },
  queued: {
    bg: 'var(--md-sys-color-tertiary-container)',
    fg: 'var(--md-sys-color-on-tertiary-container)',
    labelKey: 'status.queued',
  },
  running: {
    bg: 'var(--md-sys-color-tertiary-container)',
    fg: 'var(--md-sys-color-on-tertiary-container)',
    labelKey: 'status.running',
  },
  synthesizing: {
    bg: 'var(--md-sys-color-tertiary-container)',
    fg: 'var(--md-sys-color-on-tertiary-container)',
    labelKey: 'status.synthesizing',
  },
  completed: {
    bg: 'var(--color-th-success-container)',
    fg: 'var(--color-th-on-success-container)',
    labelKey: 'status.completed',
  },
  failed: {
    bg: 'var(--md-sys-color-error-container)',
    fg: 'var(--md-sys-color-on-error-container)',
    labelKey: 'status.failed',
  },
  blocked: {
    bg: 'var(--md-sys-color-error-container)',
    fg: 'var(--md-sys-color-on-error-container)',
    labelKey: 'runDetail.status.blockedSafety',
  },
  cancelled: {
    bg: 'var(--md-sys-color-surface-variant)',
    fg: 'var(--md-sys-color-on-surface-variant)',
    labelKey: 'status.cancelled',
  },
};

/**
 * Renders a colored pill badge for a run's lifecycle status.
 *
 * @param props The run status to display.
 */
export function RunStatusPill({status}: {status: RunStatus}) {
  const t = useT();
  const s = STYLES[status] ?? STYLES.draft;
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
      style={{backgroundColor: s.bg, color: s.fg}}
    >
      {t(s.labelKey)}
    </span>
  );
}
