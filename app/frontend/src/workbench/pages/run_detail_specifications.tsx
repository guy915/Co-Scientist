import {type ChangeEvent, useState} from 'react';
import {
  type RunFocus,
  type RunTier,
  type RunWithSummary,
  type SafetyDecision,
  adjudicateSafety,
  runGoal,
  uploadRunDocument,
} from '@/api/runs';
import {FOCUS_OPTIONS, TIER_OPTIONS} from '../run_spec';
import {
  REPORT_H3_CLASSES,
  ReportDocument,
  ReportList,
} from './run_detail_document';

// Requirements/attributes/criteria captured in a run's durable setup config,
// each defaulted to an empty list when the run has no setup yet.
function goalDetailsLists(setup: RunWithSummary['config']['setup']): {
  requirements: string[];
  attributes: string[];
  criteria: string[];
} {
  if (!setup) return {requirements: [], attributes: [], criteria: []};
  return {
    requirements: setup.requirements,
    attributes: setup.attributes,
    criteria: setup.criteria,
  };
}

// Human-readable label for a stored run tier/focus, falling back to the
// default when the value is missing or a legacy value.
function tierLabel(tier: RunTier | undefined): string {
  return TIER_OPTIONS.find(option => option.id === tier)?.label ?? 'Standard';
}

function focusLabel(focus: RunFocus | undefined): string {
  return FOCUS_OPTIONS.find(option => option.id === focus)?.label ?? 'Balance';
}

/** Run Specifications preserves the final interview contract and run mode. */
export function RunSpecificationsView({
  run,
  safety,
  onSafetyChanged,
}: {
  run: RunWithSummary | null;
  safety: SafetyDecision[];
  onSafetyChanged: () => void;
}) {
  const goal = runGoal(run) || 'Loading...';
  const {requirements, attributes, criteria} = goalDetailsLists(
    run?.config.setup,
  );

  return (
    <ReportDocument
      title="Run Specifications"
      className="cosci-run-specifications"
    >
      <p>
        <strong>Research Challenge:</strong> {goal}
      </p>
      <ReportList title="Focus Area" values={attributes} />
      <ReportList title="Preferences" values={requirements} />
      <p>
        <strong>Title:</strong> {run?.title || 'Optional'}
      </p>
      <p>
        <strong>Run type:</strong> {tierLabel(run?.config.tier)}
      </p>
      <p>
        <strong>Focus:</strong> {focusLabel(run?.config.focus)}
      </p>
      {criteria.length > 0 && (
        <p>
          <strong>Reconstruction provenance:</strong> Legacy criteria are
          retained in the stored run but are not part of the four-field Agent
          interview contract.
        </p>
      )}
      <SafetyReviewSection
        runId={run?.id}
        decisions={safety}
        onChanged={onSafetyChanged}
      />
      <PrivateCorpusUpload runId={run?.id} onChanged={onSafetyChanged} />
    </ReportDocument>
  );
}

function PrivateCorpusUpload({
  runId,
  onChanged,
}: {
  runId: string | undefined;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !runId) return;
    setBusy(true);
    setStatus(null);
    try {
      const result = await uploadRunDocument(runId, file);
      setStatus(
        `${file.name} indexed (${result.byte_size.toLocaleString()} bytes).`,
      );
      onChanged();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Private research sources</h3>
      <p>
        Upload a PDF or UTF-8 text, Markdown, CSV, or JSON document. It remains
        scoped to this run and is indexed for subsequent scientific tasks.
      </p>
      <label className="mt-3 inline-flex cursor-pointer rounded-full border border-cosci-border px-4 py-2 text-sm hover:bg-cosci-hover">
        {busy ? 'Indexing…' : 'Upload document'}
        <input
          type="file"
          className="sr-only"
          accept=".pdf,.txt,.md,.csv,.json,application/pdf,text/plain,text/markdown,text/csv,application/json"
          disabled={busy || !runId}
          onChange={event => void upload(event)}
        />
      </label>
      {status && (
        <p role="status" className="mt-2 text-sm">
          {status}
        </p>
      )}
    </section>
  );
}

function SafetyReviewSection({
  runId,
  decisions,
  onChanged,
}: {
  runId: string | undefined;
  decisions: SafetyDecision[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  if (!decisions.length) return null;

  async function resolve(
    decision: SafetyDecision,
    resolution: 'approved' | 'rejected',
  ) {
    if (!runId) return;
    setBusy(decision.id);
    try {
      await adjudicateSafety(runId, decision.id, resolution);
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Safety audit</h3>
      {decisions.map(decision => (
        <div className="mb-5" key={decision.id}>
          <p>
            <strong>{decision.stage}:</strong>{' '}
            {decision.category || decision.decision} — {decision.reason}
          </p>
          <p className="text-sm text-cosci-muted">
            Policy {decision.policy_version || 'legacy'} ·{' '}
            {decision.assessor || 'deterministic'}
          </p>
          {decision.resolution ? (
            <p>Resolution: {decision.resolution}</p>
          ) : null}
          {decision.requires_review && !decision.resolution ? (
            <div className="flex gap-2">
              <button
                className="rounded-full border border-cosci-border px-4 py-2"
                disabled={busy === decision.id}
                onClick={() => void resolve(decision, 'approved')}
                type="button"
              >
                Approve for research use
              </button>
              <button
                className="rounded-full border border-cosci-border px-4 py-2"
                disabled={busy === decision.id}
                onClick={() => void resolve(decision, 'rejected')}
                type="button"
              >
                Reject
              </button>
            </div>
          ) : null}
        </div>
      ))}
    </section>
  );
}
