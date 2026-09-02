import {type ChangeEvent, useState} from 'react';
import {
  type RunCriterion,
  type RunWithSummary,
  type SafetyDecision,
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
import {errorMessage, SafetyReviewSection} from './run_detail_safety_review';

const UPLOAD_LABEL_CLASSES =
  'mt-3 inline-flex cursor-pointer rounded-full border border-cosci-border ' +
  'px-4 py-2 text-sm hover:bg-cosci-hover';

// Requirements/attributes/criteria captured in a run's durable setup config,
// each defaulted to an empty list when the run has no setup yet.
function goalDetailsLists(setup: RunWithSummary['config']['setup']): {
  requirements: string[];
  attributes: string[];
  criteria: RunCriterion[];
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
      <SafetyReviewSection decisions={safety} />
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
