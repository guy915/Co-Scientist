import {useMemo, useState} from 'react';
import {useT} from '@/i18n';
import type {CitationRow, Evidence} from '@/api/runs';

type CitState = 'verified' | 'partial' | 'unsupported' | 'unavailable';

const STATE_STYLES: Record<CitState, {fg: string; bg: string}> = {
  verified: {
    fg: 'var(--color-th-on-success-container)',
    bg: 'var(--color-th-success-container)',
  },
  partial: {
    fg: 'var(--color-th-on-warning-container)',
    bg: 'var(--color-th-warning-container)',
  },
  unsupported: {
    fg: 'var(--color-th-destructive-on-container)',
    bg: 'var(--color-th-destructive-container)',
  },
  unavailable: {
    fg: 'var(--color-th-muted-fg)',
    bg: 'var(--color-th-muted)',
  },
};

const ALL_STATES: CitState[] = [
  'verified',
  'partial',
  'unsupported',
  'unavailable',
];

/**
 * Renders retrieved evidence with citation-state filters and summaries.
 *
 * @param props The evidence records and their citation rows.
 */
export function EvidenceTab({
  evidence,
  citations,
}: {
  evidence: Evidence[];
  citations: CitationRow[];
}) {
  const t = useT();
  const [activeStates, setActiveStates] = useState<Set<CitState>>(
    new Set(ALL_STATES),
  );

  const byEvidence = useMemo(() => {
    const map = new Map<string, CitationRow[]>();
    for (const c of citations) {
      if (!map.has(c.evidence_id)) map.set(c.evidence_id, []);
      map.get(c.evidence_id)?.push(c);
    }
    return map;
  }, [citations]);

  const stateTotals = useMemo(() => {
    const totals: Record<CitState, number> = {
      verified: 0,
      partial: 0,
      unsupported: 0,
      unavailable: 0,
    };
    for (const c of citations) totals[c.state] = (totals[c.state] ?? 0) + 1;
    return totals;
  }, [citations]);

  const filteredEvidence = useMemo(() => {
    if (activeStates.size === ALL_STATES.length) return evidence;
    return evidence.filter(e => {
      const cits = byEvidence.get(e.id) ?? [];
      if (cits.length === 0)
        return activeStates.has('unavailable') && !e.available;
      return cits.some(c => activeStates.has(c.state));
    });
  }, [evidence, byEvidence, activeStates]);

  function toggleState(s: CitState) {
    setActiveStates(prev => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      if (next.size === 0) return new Set(ALL_STATES);
      return next;
    });
  }

  if (!evidence.length) {
    return (
      <div
        className="rounded border p-6 text-sm text-center space-y-1"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          color: 'var(--md-sys-color-on-surface-variant)',
        }}
      >
        <p>{t('evidence.empty.title')}</p>
        <p className="text-xs opacity-75">{t('evidence.empty.note')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 wb-fade-in">
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {ALL_STATES.map(state => {
          const s = STATE_STYLES[state];
          const isActive = activeStates.has(state);
          const count = stateTotals[state];
          return (
            <button
              key={state}
              type="button"
              onClick={() => toggleState(state)}
              aria-pressed={isActive}
              className="rounded p-3 text-left transition-opacity"
              style={{
                backgroundColor: s.bg,
                color: s.fg,
                opacity: isActive ? 1 : 0.4,
              }}
            >
              <div className="text-xs opacity-90 capitalize">
                {t(`evidence.state.${state}`)}
              </div>
              <div className="text-2xl font-semibold">{count}</div>
            </button>
          );
        })}
      </section>

      <ul className="space-y-2">
        {filteredEvidence.map(e => {
          const cits = byEvidence.get(e.id) ?? [];
          return (
            <li
              key={e.id}
              className="rounded border p-3"
              style={{
                borderColor: 'var(--md-sys-color-outline-variant)',
                backgroundColor: 'var(--md-sys-color-surface-container-low)',
              }}
            >
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <div className="font-medium">{e.title}</div>
                  <div
                    className="text-xs"
                    style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                  >
                    {(e.authors ?? []).slice(0, 3).join(', ')}
                    {e.authors && e.authors.length > 3
                      ? t('evidence.etAl')
                      : ''}
                    {e.year ? ` · ${e.year}` : ''} · {e.source}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {!e.available && (
                    <span
                      className="text-xs px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor: 'var(--color-th-muted)',
                        color: 'var(--color-th-muted-fg)',
                      }}
                    >
                      {t('evidence.state.unavailable')}
                    </span>
                  )}
                  {e.url && (
                    <a
                      href={e.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs wb-link"
                    >
                      {t('evidence.action.open')}
                    </a>
                  )}
                </div>
              </div>
              {e.abstract && (
                <p
                  className="text-xs mt-2"
                  style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                >
                  {e.abstract}
                </p>
              )}
              {cits.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {cits.map(c => {
                    const s = STATE_STYLES[c.state];
                    return (
                      <span
                        key={c.id}
                        className="text-[11px] px-1.5 py-0.5 rounded"
                        style={{backgroundColor: s.bg, color: s.fg}}
                        title={c.claim}
                      >
                        {t(`evidence.state.${c.state}`)}
                      </span>
                    );
                  })}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
