import {type ChangeEvent, useState} from 'react';
import {
  type RunAttribute,
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
import {
  SupervisorAllocationLedger,
  type AllocationLedgerState,
} from './run_detail_supervisor_plan';

const UPLOAD_LABEL_CLASSES =
  'mt-3 inline-flex cursor-pointer rounded-full border border-cosci-border ' +
  'px-4 py-2 text-sm hover:bg-cosci-hover';

// Joins values with a trailing "or" ("A, B, or C"), matching the published
// run plan's own categorical-attribute punctuation.
function joinWithOr(values: string[]): string {
  if (values.length === 1) return values[0];
  if (values.length === 2) return `${values[0]} or ${values[1]}`;
  return `${values.slice(0, -1).join(', ')}, or ${values[values.length - 1]}`;
}

// Renders one 1-5 scaled axis, or its bare name when no anchor survives
// (an anchor need not fill every point -- see attribute_display_strings).
function scaledDisplayString(
  name: string,
  scale: {'1'?: string; '3'?: string; '5'?: string},
): string {
  const anchors = (['1', '3', '5'] as const)
    .filter(point => scale[point])
    .map(point => `${point}: ${scale[point]}`);
  return anchors.length ? `${name}: 1-5 scale (${anchors.join(', ')})` : name;
}

// Renders one categorical axis, or its bare name when no option survives.
function categoricalDisplayString(name: string, values: string[]): string {
  const options = (values ?? []).filter(Boolean);
  return options.length ? `${name} (${joinWithOr(options)})` : name;
}

// Renders one attribute setup item -- the legacy free-prose string, or the
// R12-5 structured axis shape -- as a single display string, mirroring
// app.run_modes_attributes.attribute_display_strings on the backend so a
// stored run reads the same way here as in the report and Goal Details.
export function attributeDisplayString(item: RunAttribute): string {
  if (typeof item === 'string') return item;
  if ('scale' in item) return scaledDisplayString(item.name, item.scale);
  return categoricalDisplayString(item.name, item.values);
}

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
    attributes: setup.attributes.map(attributeDisplayString),
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
  allocationLedger,
  onSafetyChanged,
}: {
  run: RunWithSummary | null;
  safety: SafetyDecision[];
  allocationLedger: AllocationLedgerState;
  onSafetyChanged: () => void;
}) {
  return (
    <ReportDocument
      title="Run Specifications"
      className="cosci-run-specifications"
    >
      <SpecFields run={run} />
      <div className="mt-6">
        <SupervisorAllocationLedger {...allocationLedger} />
      </div>
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
