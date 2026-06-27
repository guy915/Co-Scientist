import '@material/web/icon/icon.js';
import type {
  Evidence,
  Hypothesis,
  MatchRow,
  Report,
  RunWithSummary,
  SafetyDecision,
} from '@/api/runs';

function fmtNumber(value: number | null | undefined): string {
  return typeof value === 'number' ? String(value) : '0';
}

function fmtDate(value: number | null | undefined): string {
  if (!value) return 'Not available';
  return new Date(value * 1000).toLocaleString();
}

/**
 * Shows the concrete run configuration and stored artifact counts.
 */
export function RunSpecificationsTab({
  run,
  hypotheses,
  evidence,
  matches,
  safety,
  report,
}: {
  run: RunWithSummary | null;
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  matches: MatchRow[];
  safety: SafetyDecision[];
  report: Report | null;
}) {
  if (!run) {
    return (
      <div
        className="rounded border p-6 text-sm text-center"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          color: 'var(--md-sys-color-on-surface-variant)',
        }}
      >
        Run specifications will appear once the run loads.
      </div>
    );
  }

  const generated = hypotheses.filter(h => !h.parent_id).length;
  const evolved = hypotheses.filter(h => h.parent_id).length;
  const verifiedCitations = report?.payload.citation_summary?.verified ?? 0;
  const setup = run.config.setup;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
      <section
        className="rounded border p-4"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          backgroundColor: 'var(--md-sys-color-surface-container-low)',
        }}
      >
        <h2 className="mb-3 text-base font-semibold">Run setup</h2>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <Spec label="Status" value={run.status} />
          <Spec
            label="Focus"
            value={setup?.focus ?? run.config.focus ?? 'balance'}
          />
          <Spec
            label="Tier"
            value={setup?.tier ?? run.config.tier ?? 'standard'}
          />
          <Spec label="Created" value={fmtDate(run.created_at)} />
          <Spec label="Updated" value={fmtDate(run.updated_at)} />
        </dl>
        {setup && (
          <div className="mt-4 space-y-3">
            <SetupList label="Requirements" values={setup.requirements} />
            <SetupList label="Attributes" values={setup.attributes} />
            <SetupList label="Criteria" values={setup.criteria} />
          </div>
        )}
      </section>

      <section
        className="rounded border p-4"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          backgroundColor: 'var(--md-sys-color-surface-container-low)',
        }}
      >
        <h2 className="mb-3 text-base font-semibold">Configured workflow</h2>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <Spec
            label="Initial hypotheses"
            value={fmtNumber(run.config.initial_hypotheses_count as number)}
          />
          <Spec
            label="Iterations"
            value={fmtNumber(run.config.max_iterations as number)}
          />
          <Spec
            label="Evolution count"
            value={fmtNumber(run.config.evolution_max_count as number)}
          />
          <Spec
            label="Tournament pairs"
            value={fmtNumber(run.config.tournament_pairs as number)}
          />
          <Spec
            label="Literature count"
            value={fmtNumber(
              run.config.literature_review_papers_count as number,
            )}
          />
          <Spec
            label="K-factor"
            value={fmtNumber(run.config.k_factor as number)}
          />
        </dl>
      </section>

      <section
        className="rounded border p-4"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          backgroundColor: 'var(--md-sys-color-surface-container-low)',
        }}
      >
        <h2 className="mb-3 text-base font-semibold">Artifacts</h2>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <Spec label="Generated hypotheses" value={fmtNumber(generated)} />
          <Spec label="Evolved hypotheses" value={fmtNumber(evolved)} />
          <Spec label="Knowledge sources" value={fmtNumber(evidence.length)} />
          <Spec label="Tournament matches" value={fmtNumber(matches.length)} />
          <Spec
            label="Verified citations"
            value={fmtNumber(verifiedCitations)}
          />
          <Spec label="Stored events" value={fmtNumber(run.summary?.events)} />
        </dl>
      </section>

      <section
        className="rounded border p-4"
        style={{
          borderColor: 'var(--md-sys-color-outline-variant)',
          backgroundColor: 'var(--md-sys-color-surface-container-low)',
        }}
      >
        <h2 className="mb-3 text-base font-semibold">Safety gates</h2>
        {safety.length ? (
          <ul className="space-y-2 text-sm">
            {safety.map(decision => (
              <li
                key={`${decision.stage}-${decision.created_at}`}
                className="rounded border p-2"
                style={{
                  borderColor: 'var(--md-sys-color-outline-variant)',
                }}
              >
                <div className="font-medium capitalize">
                  {decision.stage}: {decision.decision}
                </div>
                <div
                  className="text-xs"
                  style={{color: 'var(--md-sys-color-on-surface-variant)'}}
                >
                  {decision.reason || 'No safety issue detected.'}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p
            className="text-sm"
            style={{color: 'var(--md-sys-color-on-surface-variant)'}}
          >
            Safety decisions have not been recorded yet.
          </p>
        )}
      </section>
    </div>
  );
}

function Spec({label, value}: {label: string; value: string}) {
  return (
    <div>
      <dt
        className="text-xs uppercase tracking-wide"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
      >
        {label}
      </dt>
      <dd className="mt-1 font-medium capitalize">{value}</dd>
    </div>
  );
}

function SetupList({label, values}: {label: string; values: string[]}) {
  if (!values.length) return null;
  return (
    <div>
      <div
        className="mb-1 text-xs uppercase tracking-wide"
        style={{color: 'var(--md-sys-color-on-surface-variant)'}}
      >
        {label}
      </div>
      <ul className="space-y-1 text-sm">
        {values.map(value => (
          <li key={value} className="flex gap-2">
            <md-icon style={{fontSize: '16px'}} aria-hidden="true">
              check_circle
            </md-icon>
            <span>{value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
