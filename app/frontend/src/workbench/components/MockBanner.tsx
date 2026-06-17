import '@material/web/icon/icon.js';
import {useEffect, useState} from 'react';
import {getSystemStatus, type SystemStatus} from '@/api/runs';
import {useT} from '@/i18n';

/**
 * Renders a footer banner indicating live-engine or offline mock mode.
 */
export function MockBanner() {
  const t = useT();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  useEffect(() => {
    let cancelled = false;
    getSystemStatus()
      .then(s => {
        if (!cancelled) setStatus(s);
      })
      .catch(() => {
        /* swallow — banner is non-critical */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!status) return null;
  if (!status.mock_mode) {
    return (
      <div
        className="text-xs px-6 py-1 border-t"
        style={{
          backgroundColor: 'var(--md-sys-color-secondary-container)',
          color: 'var(--md-sys-color-on-surface-variant)',
          borderColor: 'var(--md-sys-color-outline-variant)',
        }}
      >
        {t('runDetail.banner.liveMode')} &middot;{' '}
        {t('runDetail.banner.provider')} <strong>{status.provider}</strong>{' '}
        &middot; {t('runDetail.banner.model')}{' '}
        <strong className="force-ltr">{status.model_name}</strong>
      </div>
    );
  }
  return (
    <div
      role="status"
      className="text-xs px-6 py-1.5 border-t flex items-center gap-2"
      style={{
        backgroundColor:
          'color-mix(in srgb, var(--color-th-warning) 18%, transparent)',
        color: 'var(--md-sys-color-on-surface)',
        borderColor: 'var(--md-sys-color-outline-variant)',
      }}
    >
      <md-icon aria-hidden="true" style={{fontSize: '14px'}}>
        warning
      </md-icon>
      <span>
        <strong>{t('runDetail.banner.mockTitle')}</strong>
        {t('runDetail.banner.mockBody')}
        <code className="force-ltr">GEMINI_API_KEY</code> /{' '}
        <code className="force-ltr">OPENAI_API_KEY</code> /{' '}
        <code className="force-ltr">ANTHROPIC_API_KEY</code>
        {t('runDetail.banner.mockBodyEnd')}
        <code className="force-ltr">.env</code>
        {t('runDetail.banner.mockBodyTail')}
      </span>
    </div>
  );
}
