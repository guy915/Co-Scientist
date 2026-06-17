import type {
  Evidence,
  Hypothesis,
  MatchRow,
  RunWithSummary,
  SafetyDecision,
} from '@/api/runs';
import type {StreamEvent} from '@/hooks/use_run_stream';

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

function fmtAgent(t: string) {
  return AGENT_LABELS[t] ?? t.replace(/[._]/g, ' ');
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
  const blocked = safety.find(s => s.decision === 'block');
  const dualUse = safety.find(s => s.decision === 'redact');
  const initialCount = hypotheses.filter(h => !h.parent_id).length;
  const evolvedCount = hypotheses.filter(h => h.parent_id).length;
  const topElo = hypotheses[0]?.elo_rating ?? 1200;

  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <aside className="grid grid-cols-2 gap-2 lg:hidden">
        <Stat
          label="Hypotheses"
          value={hypotheses.length}
          sub={`${initialCount} initial · ${evolvedCount} evolved`}
        />
        <Stat
          label="Top Elo"
          value={topElo}
          sub={`from ${matches.length} matches`}
        />
        <Stat label="Evidence sources" value={evidence.length} />
        <Stat
          label="Pipeline events"
          value={events.length}
          sub={
            run
              ? `${run.summary?.events ?? events.length} persisted`
              : undefined
          }
        />
      </aside>

      <div className="space-y-4 lg:col-span-2">
        <Section title="Pipeline timeline">
          {events.length === 0 ? (
            <p className="text-sm" style={{color: 'var(--color-th-muted-fg)'}}>
              Waiting for events…
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
                    {fmtAgent(e.type)}
                  </span>
                  <span
                    style={{color: 'var(--color-th-muted-fg)'}}
                    className="min-w-0 text-xs leading-relaxed sm:flex-1 sm:truncate sm:text-sm"
                  >
                    {summarizeEventPayload(e)}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Section>

        {(blocked || dualUse) && (
          <Section title="Safety decisions">
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
          label="Hypotheses"
          value={hypotheses.length}
          sub={`${initialCount} initial · ${evolvedCount} evolved`}
        />
        <Stat
          label="Top Elo"
          value={topElo}
          sub={`from ${matches.length} matches`}
        />
        <Stat label="Evidence sources" value={evidence.length} />
        <Stat
          label="Pipeline events"
          value={events.length}
          sub={
            run
              ? `${run.summary?.events ?? events.length} persisted`
              : undefined
          }
        />
      </aside>
    </div>
  );
}

function summarizeEventPayload(e: StreamEvent): string {
  const p = e.payload as Record<string, unknown>;
  if (e.type === 'generate')
    return `${(p.hypotheses as unknown[] | undefined)?.length ?? 0} initial hypotheses`;
  if (e.type === 'evolve')
    return `${(p.children as unknown[] | undefined)?.length ?? 0} evolved children`;
  if (e.type === 'ranking')
    return `iter ${p.iteration as number} · ${(p.matches as unknown[] | undefined)?.length ?? 0} matches`;
  if (e.type === 'literature_review')
    return `${(p.evidence as unknown[] | undefined)?.length ?? 0} sources`;
  if (e.type === 'citation_audit')
    return `${p.verified as number} verified · ${p.partial as number} partial · ${p.unsupported as number} unsupported · ${p.unavailable as number} unavailable`;
  if (e.type === 'safety.intake' || e.type === 'safety.final')
    return String(p.decision ?? '');
  if (e.type === 'status') return String(p.status ?? '');
  if (e.type === 'report') return 'report saved';
  if (e.type === 'meta_review') return `iter ${p.iteration as number} critique`;
  if (e.type === 'supervisor.plan')
    return `plan with ${((p.agents as unknown[] | undefined) ?? []).length} agents`;
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
