import type {
  Evidence,
  Hypothesis,
  MatchRow,
  RunWithSummary,
  SafetyDecision,
} from '@/api/runs';
import type {StreamEvent} from '@/hooks/useRunStream';
import {useT} from '@/i18n';
import type {TFunction} from '@/i18n';

const AGENT_LABELS: Record<string, string> = {
  'supervisor.plan': 'Supervisor',
  'intake.scope': 'Intake',
  'safety.intake': 'Safety (intake)',
  literature_review: 'Literature retrieval',
  generate: 'Generation',
  reflection: 'Reflection',
  proximity: 'Proximity',
  ranking: 'Ranking',
  evolve: 'Evolution',
  meta_review: 'Meta-review',
  citation_audit: 'Citation audit',
  'safety.final': 'Safety (final)',
  report: 'Report synthesis',
  status: 'Status',
  lifecycle: 'Lifecycle',
};

function fmtAgent(t: TFunction, type: string) {
  if (type in AGENT_LABELS) return t(`overview.agent.${type}`);
  return type.replace(/[._]/g, ' ');
}

/**
 * Renders the run summary: pipeline timeline, safety decisions, and stats.
 *
 * @param props The run plus its hypotheses, evidence, matches, safety
 *   decisions, and streamed pipeline events.
 */
export function OverviewTab({
  run,
  hypotheses,
  evidence,
  matches,
  safety,
  events,
}: {
  run: RunWithSummary | null;
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  matches: MatchRow[];
  safety: SafetyDecision[];
  events: StreamEvent[];
}) {
  const t = useT();
  const blocked = safety.find(s => s.decision === 'block');
  const dualUse = safety.find(s => s.decision === 'redact');
  const initialCount = hypotheses.filter(h => !h.parent_id).length;
  const evolvedCount = hypotheses.filter(h => h.parent_id).length;
  const topElo = hypotheses[0]?.elo_rating ?? 1200;

  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <aside className="grid grid-cols-2 gap-2 lg:hidden">
        <Stat
          label={t('label.hypotheses')}
          value={hypotheses.length}
          sub={t('overview.stat.hypothesesSub', {
            initial: initialCount,
            evolved: evolvedCount,
          })}
        />
        <Stat
          label={t('overview.stat.topElo')}
          value={topElo}
          sub={t('overview.stat.topEloSub', {matches: matches.length})}
        />
        <Stat
          label={t('overview.stat.evidenceSources')}
          value={evidence.length}
        />
        <Stat
          label={t('overview.stat.pipelineEvents')}
          value={events.length}
          sub={
            run
              ? t('overview.stat.eventsSub', {
                  events: run.summary?.events ?? events.length,
                })
              : undefined
          }
        />
      </aside>

      <div className="space-y-4 lg:col-span-2">
        <Section title={t('overview.section.timeline')}>
          {events.length === 0 ? (
            <p className="text-sm" style={{color: 'var(--color-th-muted-fg)'}}>
              {t('overview.timeline.waiting')}
            </p>
          ) : (
            <ol className="space-y-2 text-sm">
              {events.map(e => (
                <li
                  key={e.seq}
                  className="grid grid-cols-[2rem_1fr] gap-x-3 gap-y-0.5 rounded-lg border p-2.5 sm:flex sm:flex-wrap sm:border-0 sm:p-0"
                  style={{borderColor: 'var(--color-th-border)'}}
                >
                  <span
                    className="row-span-2 font-mono text-xs text-right sm:w-8 sm:shrink-0"
                    style={{color: 'var(--color-th-muted-fg)'}}
                  >
                    {e.seq}
                  </span>
                  <span className="min-w-0 font-medium sm:w-44 sm:shrink-0">
                    {fmtAgent(t, e.type)}
                  </span>
                  <span
                    style={{color: 'var(--color-th-muted-fg)'}}
                    className="min-w-0 text-xs leading-relaxed sm:flex-1 sm:truncate sm:text-sm"
                  >
                    {summarizeEventPayload(t, e)}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Section>

        {(blocked || dualUse) && (
          <Section title={t('overview.section.safety')}>
            <ul className="space-y-2 text-sm">
              {safety.map(s => (
                <li
                  key={`${s.stage}-${s.created_at}`}
                  className="rounded border p-2"
                  style={{
                    borderColor:
                      s.decision === 'block'
                        ? 'var(--color-th-destructive)'
                        : s.decision === 'redact'
                          ? 'var(--color-th-warning)'
                          : 'var(--color-th-border)',
                  }}
                >
                  <strong className="capitalize">{s.stage}</strong> ·{' '}
                  {s.decision}
                  {s.reason && (
                    <div
                      className="text-xs"
                      style={{color: 'var(--color-th-muted-fg)'}}
                    >
                      {s.reason}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>

      <aside className="hidden lg:block lg:space-y-3">
        <Stat
          label={t('label.hypotheses')}
          value={hypotheses.length}
          sub={t('overview.stat.hypothesesSub', {
            initial: initialCount,
            evolved: evolvedCount,
          })}
        />
        <Stat
          label={t('overview.stat.topElo')}
          value={topElo}
          sub={t('overview.stat.topEloSub', {matches: matches.length})}
        />
        <Stat
          label={t('overview.stat.evidenceSources')}
          value={evidence.length}
        />
        <Stat
          label={t('overview.stat.pipelineEvents')}
          value={events.length}
          sub={
            run
              ? t('overview.stat.eventsSub', {
                  events: run.summary?.events ?? events.length,
                })
              : undefined
          }
        />
      </aside>
    </div>
  );
}

function summarizeEventPayload(t: TFunction, e: StreamEvent): string {
  const p = e.payload as Record<string, unknown>;
  if (e.type === 'generate')
    return t('overview.event.generate', {
      n: (p.hypotheses as unknown[] | undefined)?.length ?? 0,
    });
  if (e.type === 'evolve')
    return t('overview.event.evolve', {
      n: (p.children as unknown[] | undefined)?.length ?? 0,
    });
  if (e.type === 'ranking')
    return t('overview.event.ranking', {
      iteration: p.iteration as number,
      n: (p.matches as unknown[] | undefined)?.length ?? 0,
    });
  if (e.type === 'literature_review')
    return t('overview.event.literature_review', {
      n: (p.evidence as unknown[] | undefined)?.length ?? 0,
    });
  if (e.type === 'citation_audit')
    return t('overview.event.citation_audit', {
      verified: p.verified as number,
      partial: p.partial as number,
      unsupported: p.unsupported as number,
      unavailable: p.unavailable as number,
    });
  if (e.type === 'safety.intake' || e.type === 'safety.final')
    return String(p.decision ?? '');
  if (e.type === 'status') return String(p.status ?? '');
  if (e.type === 'report') return t('overview.event.report');
  if (e.type === 'meta_review')
    return t('overview.event.meta_review', {iteration: p.iteration as number});
  if (e.type === 'supervisor.plan')
    return t('overview.event.supervisor.plan', {
      n: ((p.agents as unknown[] | undefined) ?? []).length,
    });
  if (e.type === 'lifecycle') return String(p.event ?? '');
  return '';
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="rounded border p-4"
      style={{
        borderColor: 'var(--color-th-border)',
        backgroundColor: 'var(--color-th-card)',
      }}
    >
      <h2 className="font-semibold mb-3 text-sm uppercase tracking-wide">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: number | string;
  sub?: string;
}) {
  return (
    <div
      className="rounded border p-3"
      style={{
        borderColor: 'var(--color-th-border)',
        backgroundColor: 'var(--color-th-card)',
      }}
    >
      <div
        className="text-xs uppercase tracking-wide"
        style={{color: 'var(--color-th-muted-fg)'}}
      >
        {label}
      </div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
      {sub && (
        <div
          className="text-xs mt-0.5"
          style={{color: 'var(--color-th-muted-fg)'}}
        >
          {sub}
        </div>
      )}
    </div>
  );
}
