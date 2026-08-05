import {type ChangeEvent, useState} from 'react';
import {
  type RunWithSummary,
  type SafetyDecision,
  adjudicateSafety,
  isTerminalStatus,
  runGoal,
  uploadRunDocument,
} from '@/api/runs';
import {FOCUS_OPTIONS, TIER_OPTIONS, runOptionLabel} from '../run_spec';
import {
  REPORT_H3_CLASSES,
  ReportDocument,
  ReportList,
} from './run_detail_document';

const UPLOAD_LABEL_CLASSES =
  'mt-3 inline-flex cursor-pointer rounded-full border border-cosci-border ' +
  'px-4 py-2 text-sm hover:bg-cosci-hover';

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

// The run-option display labels SpecFields needs: title, tier, and focus,
// each defaulted for a run that has not set one.
function specRunLabels(run: RunWithSummary | null): {
  title: string;
  tier: string;
  focus: string;
} {
  return {
    title: run?.title || 'Optional',
    tier: runOptionLabel(TIER_OPTIONS, run?.config.tier, 'Standard'),
    focus: runOptionLabel(FOCUS_OPTIONS, run?.config.focus, 'Balance'),
  };
}

// Every display value SpecFields needs, resolved up front so the component
// itself does no defaulting or lookup of its own.
function specDisplayValues(run: RunWithSummary | null) {
  const {requirements, attributes, criteria} = goalDetailsLists(
    run?.config.setup,
  );
  return {
    goal: runGoal(run) || 'Loading...',
    requirements,
    attributes,
    criteria,
    ...specRunLabels(run),
  };
}

// The interview-contract fields: goal, lists, title, and run options.
function SpecFields({run}: {run: RunWithSummary | null}) {
  const {goal, requirements, attributes, criteria, title, tier, focus} =
    specDisplayValues(run);
  return (
    <>
      <p>
        <strong>Research Challenge:</strong> {goal}
      </p>
      <ReportList title="Focus Area" values={attributes} />
      <ReportList title="Preferences" values={requirements} />
      <p>
        <strong>Title:</strong> {title}
      </p>
      <p>
        <strong>Run type:</strong> {tier}
      </p>
      <p>
        <strong>Focus:</strong> {focus}
      </p>
      {criteria.length > 0 && (
        <p>
          <strong>Reconstruction provenance:</strong> Legacy criteria are
          retained in the stored run but are not part of the four-field Agent
          interview contract.
        </p>
      )}
    </>
  );
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
  return (
    <ReportDocument
      title="Run Specifications"
      className="cosci-run-specifications"
    >
      <SpecFields run={run} />
      <SafetyReviewSection
        runId={run?.id}
        decisions={safety}
        onChanged={onSafetyChanged}
      />
      {run && !isTerminalStatus(run.status) && (
        <PrivateCorpusUpload runId={run.id} onChanged={onSafetyChanged} />
      )}
    </ReportDocument>
  );
}

const UPLOAD_ACCEPT =
  '.pdf,.txt,.md,.csv,.json,application/pdf,text/plain,text/markdown,' +
  'text/csv,application/json';

interface UploadCallbacks {
  setBusy: (busy: boolean) => void;
  setStatus: (status: string | null) => void;
  onChanged: () => void;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// Uploads the chosen file into the run's private corpus, reporting progress
// and outcome through the given callbacks.
async function uploadCorpusFile(
  event: ChangeEvent<HTMLInputElement>,
  runId: string | undefined,
  callbacks: UploadCallbacks,
) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file || !runId) return;
  callbacks.setBusy(true);
  callbacks.setStatus(null);
  try {
    const result = await uploadRunDocument(runId, file);
    callbacks.setStatus(
      `${file.name} indexed (${result.byte_size.toLocaleString()} bytes).`,
    );
    callbacks.onChanged();
  } catch (error) {
    callbacks.setStatus(errorMessage(error));
  } finally {
    callbacks.setBusy(false);
  }
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

  const upload = (event: ChangeEvent<HTMLInputElement>) =>
    uploadCorpusFile(event, runId, {setBusy, setStatus, onChanged});

  return (
    <section className="mt-8 border-t border-cosci-border pt-5">
      <h3 className={REPORT_H3_CLASSES}>Private research sources</h3>
      <p>
        Upload a PDF or UTF-8 text, Markdown, CSV, or JSON document. It remains
        scoped to this run and is indexed for subsequent scientific tasks.
      </p>
      <label className={UPLOAD_LABEL_CLASSES}>
        {busy ? 'Indexing…' : 'Upload document'}
        <input
          type="file"
          className="sr-only"
          accept={UPLOAD_ACCEPT}
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

interface ResolveProps {
  busy: boolean;
  onResolve: (resolution: 'approved' | 'rejected') => void;
}

// The approve/reject controls for a decision still awaiting human review.
function ResolveButtons({busy, onResolve}: ResolveProps) {
  return (
    <div className="flex gap-2">
      <button
        className="rounded-full border border-cosci-border px-4 py-2"
        disabled={busy}
        onClick={() => onResolve('approved')}
        type="button"
      >
        Approve for research use
      </button>
      <button
        className="rounded-full border border-cosci-border px-4 py-2"
        disabled={busy}
        onClick={() => onResolve('rejected')}
        type="button"
      >
        Reject
      </button>
    </div>
  );
}

// Display values derived from a safety decision: the human-readable category
// when one was assigned, plus whether it still needs a human resolution. The
// policy version and assessor are decision-internal plumbing and are not
// surfaced here.
function decisionDisplayValues(decision: SafetyDecision) {
  return {
    category: decision.category,
    needsResolution: decision.requires_review && !decision.resolution,
    // A hypothesis the engine's safety screen held out of the pool. It has
    // no hypothesis row of its own, so its decision row is the one place a
    // person can see the idea and adjudicate it.
    heldHypothesis:
      decision.stage === 'hypothesis' && decision.decision === 'hold',
  };
}

// One safety decision: what was flagged and — when it still needs human
// review — the approve/reject controls.
function SafetyDecisionItem({
  decision,
  busy,
  onResolve,
}: ResolveProps & {decision: SafetyDecision}) {
  const {category, needsResolution, heldHypothesis} =
    decisionDisplayValues(decision);
  return (
    <div className="mb-5">
      {heldHypothesis ? (
        <p>
          <strong>Held for review:</strong> {decision.reason}
        </p>
      ) : (
        <p>
          <strong>{decision.stage}:</strong>{' '}
          {category ? `${category} — ${decision.reason}` : decision.reason}
        </p>
      )}
      {decision.resolution ? <p>Resolution: {decision.resolution}</p> : null}
      {needsResolution ? (
        <ResolveButtons busy={busy} onResolve={onResolve} />
      ) : null}
    </div>
  );
}

// The verdict of the final screen, which is what the audit reads as: one
// per-run row appended after every hypothesis has been gated. Decisions
// arrive oldest-first, so the last matching row is the current one.
function finalDecision(decisions: SafetyDecision[]) {
  const finals = decisions.filter(d => d.stage === 'final');
  return finals.length ? finals[finals.length - 1] : null;
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
  // The audit is dominated by routine per-hypothesis claim-gate rows that say
  // nothing about the run as a whole, so only the final verdict is shown.
  // Decisions a human must adjudicate are the exception: they carry the
  // approve/reject controls, and hiding them would strand the review.
  const summary = finalDecision(decisions);
  const reviewable = decisions.filter(
    d => d.requires_review && d.id !== summary?.id,
  );
  if (!summary && !reviewable.length) return null;

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
      {summary ? <p className="mb-5">{summary.reason}</p> : null}
      {reviewable.map(decision => (
        <SafetyDecisionItem
          key={decision.id}
          decision={decision}
          busy={busy === decision.id}
          onResolve={resolution => void resolve(decision, resolution)}
        />
      ))}
    </section>
  );
}
