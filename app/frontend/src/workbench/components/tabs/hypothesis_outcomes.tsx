import {useState, type FormEvent} from 'react';
import {addHypothesisOutcome} from '@/api/runs';
import type {Hypothesis, HypothesisOutcome} from '@/api/runs';
import {
  ReportDocument,
  REPORT_H4_CLASSES,
} from '@/workbench/pages/run_detail_document';

const FIELD_CLASSES =
  'w-full rounded-md border border-cosci-border bg-cosci-bg px-3 py-2 ' +
  'text-sm text-cosci-fg focus-visible:outline-2 ' +
  'focus-visible:outline-cosci-accent';

interface OutcomeCollectionProps {
  outcomes?: HypothesisOutcome[];
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => Promise<void> | void;
}

type ReadyOutcomeCollectionProps = Omit<
  OutcomeCollectionProps,
  'outcomes' | 'loading' | 'error'
> & {
  outcomes: HypothesisOutcome[];
  loading: boolean;
  error: string | null;
};

const EMPTY_OUTCOMES: HypothesisOutcome[] = [];

function resolvedCollectionState({
  outcomes,
  loading,
  error,
}: OutcomeCollectionProps) {
  return {
    outcomes: outcomes ?? EMPTY_OUTCOMES,
    loading: loading ?? false,
    error: error ?? null,
  };
}

/** Scientist-entered observation form and list for one selected hypothesis. */
export function HypothesisOutcomeSection({
  runId,
  hypothesis,
  outcomes,
  loading,
  error,
  readOnly,
  onRefresh,
}: OutcomeCollectionProps & {
  runId: string;
  hypothesis: Hypothesis;
  readOnly?: boolean;
  onRefresh: () => Promise<void> | void;
}) {
  const state = resolvedCollectionState({outcomes, loading, error, onRefresh});
  const matching = state.outcomes.filter(
    outcome => outcome.hypothesis_id === hypothesis.id,
  );

  return (
    <section className="grid gap-3" aria-busy={state.loading}>
      <h2 className="font-gsans text-[1.5rem] leading-8 font-normal">
        Scientist-recorded observations
      </h2>
      <p className="text-sm text-cosci-muted">
        These observations are entered by a scientist and are not independently
        validated.
      </p>
      <OutcomeCollectionState
        outcomes={matching}
        loading={state.loading}
        error={state.error}
        onRefresh={onRefresh}
        emptyText="No observations have been recorded for this hypothesis."
      />
      {readOnly ? (
        <p role="note" className="text-sm text-cosci-muted">
          Public demo observations are read-only.
        </p>
      ) : (
        <OutcomeSubmissionForm
          runId={runId}
          hypothesisId={hypothesis.id}
          onRefresh={onRefresh}
        />
      )}
    </section>
  );
}

function OutcomeSubmissionForm({
  runId,
  hypothesisId,
  onRefresh,
}: {
  runId: string;
  hypothesisId: string;
  onRefresh: () => Promise<void> | void;
}) {
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setSaving(true);
    setSubmitError(null);
    setSaved(false);
    try {
      await addHypothesisOutcome(runId, hypothesisId, {
        method_protocol: String(form.get('method_protocol')).trim(),
        conditions: String(form.get('conditions')).trim(),
        measured_observation: String(form.get('measured_observation')).trim(),
        units: String(form.get('units')).trim() || undefined,
        controls: String(form.get('controls')).trim(),
        interpretation: String(form.get('interpretation')).trim(),
        referenced_evidence_ids: String(form.get('referenced_evidence_ids'))
          .split(/[\n,]/)
          .map(id => id.trim())
          .filter(Boolean),
      });
      formElement.reset();
      setSaved(true);
      await onRefresh();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="grid gap-3 border-t border-cosci-border pt-4"
      onSubmit={submit}
      aria-busy={saving}
    >
      <fieldset disabled={saving} className="grid gap-3">
        <legend className="text-base font-medium">Record an observation</legend>
        <TextField name="method_protocol" label="Method or protocol" required />
        <TextField name="conditions" label="Conditions" required />
        <TextField
          name="measured_observation"
          label="Measured observation"
          required
        />
        <TextField name="units" label="Units (optional)" />
        <TextField name="controls" label="Controls" required />
        <TextField name="interpretation" label="Interpretation" required />
        <TextField
          name="referenced_evidence_ids"
          label="Referenced evidence IDs"
          hint="Separate IDs with commas or new lines."
        />
        <button
          type="submit"
          className="w-fit rounded-full bg-cosci-teal px-5 py-3 text-sm font-medium text-white disabled:opacity-60"
        >
          {saving ? 'Saving observation…' : 'Record observation'}
        </button>
      </fieldset>
      {submitError && <p role="alert">{submitError}</p>}
      {saved && <p role="status">Observation recorded.</p>}
    </form>
  );
}

/** Post-publication observations kept visually separate from report claims. */
export function RunOutcomesReport({
  outcomes,
  hypotheses,
  loading,
  error,
  onRefresh,
}: OutcomeCollectionProps & {hypotheses: Hypothesis[]}) {
  const state = resolvedCollectionState({outcomes, loading, error, onRefresh});
  const titleById = new Map(hypotheses.map(item => [item.id, item.title]));
  return (
    <ReportDocument title="Scientist-recorded empirical outcomes">
      <p className="text-sm text-cosci-muted">
        Post-publication observations entered by researchers. They are not
        independently validated and do not change the generated report,
        hypothesis scores, or reviews.
      </p>
      <OutcomeCollectionState
        outcomes={state.outcomes}
        loading={state.loading}
        error={state.error}
        onRefresh={onRefresh}
        emptyText="No scientist-recorded observations have been added to this run."
        titleById={titleById}
      />
    </ReportDocument>
  );
}

function OutcomeCollectionState({
  outcomes,
  loading,
  error,
  onRefresh,
  emptyText,
  titleById,
}: ReadyOutcomeCollectionProps & {
  emptyText: string;
  titleById?: Map<string, string>;
}) {
  const newestFirst = [...outcomes].sort(
    (left, right) => right.recorded_at - left.recorded_at,
  );
  return (
    <div className="grid gap-3">
      <OutcomeLoading loading={loading} />
      <OutcomeError error={error} />
      <OutcomeEmpty
        visible={!loading && !error && newestFirst.length === 0}
        text={emptyText}
      />
      {newestFirst.map(outcome => (
        <OutcomeCard
          key={outcome.id}
          outcome={outcome}
          hypothesisTitle={
            titleById?.get(outcome.hypothesis_id) ??
            outcome.hypothesis_snapshot?.title ??
            outcome.hypothesis_id
          }
        />
      ))}
      <button
        type="button"
        onClick={() => void onRefresh?.()}
        disabled={loading || !onRefresh}
        className="w-fit rounded-full border border-cosci-border px-4 py-2 text-sm font-medium disabled:opacity-60"
      >
        {loading ? 'Refreshing observations…' : 'Refresh observations'}
      </button>
    </div>
  );
}

function OutcomeLoading({loading}: {loading: boolean}) {
  if (!loading) return null;
  return (
    <p role="status" className="text-sm text-cosci-muted">
      Loading observations…
    </p>
  );
}

function OutcomeError({error}: {error: string | null}) {
  if (!error) return null;
  return <p role="alert">Could not load observations: {error}</p>;
}

function OutcomeEmpty({visible, text}: {visible: boolean; text: string}) {
  if (!visible) return null;
  return <p className="text-sm text-cosci-muted">{text}</p>;
}

function OutcomeCard({
  outcome,
  hypothesisTitle,
}: {
  outcome: HypothesisOutcome;
  hypothesisTitle?: string;
}) {
  const recordedDate = new Date(outcome.recorded_at * 1000);
  return (
    <article className="grid gap-2 rounded-md border border-cosci-border p-4">
      <p className="text-sm text-cosci-muted">
        <strong>{outcome.author}</strong>
        {' · '}
        <time dateTime={recordedDate.toISOString()}>
          {recordedDate.toLocaleString()}
        </time>
        {hypothesisTitle && <> · {hypothesisTitle}</>}
      </p>
      <dl className="grid gap-2 text-sm">
        <OutcomeDetail
          label="Method or protocol"
          value={outcome.method_protocol}
        />
        <OutcomeDetail label="Conditions" value={outcome.conditions} />
        <OutcomeDetail
          label="Measured observation"
          value={outcome.measured_observation}
        />
        {outcome.units && <OutcomeDetail label="Units" value={outcome.units} />}
        <OutcomeDetail label="Controls" value={outcome.controls} />
        <OutcomeDetail label="Interpretation" value={outcome.interpretation} />
      </dl>
      <OutcomeReferences outcome={outcome} />
    </article>
  );
}

function OutcomeReferences({outcome}: {outcome: HypothesisOutcome}) {
  const references = outcome.referenced_evidence;
  const ids = outcome.referenced_evidence_ids;
  if (references?.length) {
    return (
      <div>
        <h4 className={REPORT_H4_CLASSES}>Referenced evidence</h4>
        <ul className="flex flex-wrap gap-2">
          {references.map(evidence => (
            <li key={evidence.id} className="grid gap-1">
              <p>
                <EvidenceTitle evidence={evidence} />
                {' · '}
                {evidence.source}
              </p>
              <p className="text-xs text-cosci-muted">
                <code>{evidence.id}</code>
                {evidence.doi && <> · DOI {evidence.doi}</>}
                {evidence.pmid && <> · PMID {evidence.pmid}</>}
                {evidence.sha256 && <> · SHA-256 {evidence.sha256}</>}
              </p>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  if (!ids.length) return null;
  return (
    <div>
      <h4 className={REPORT_H4_CLASSES}>Referenced evidence</h4>
      <ul className="flex flex-wrap gap-2">
        {ids.map(id => (
          <li key={id}>
            <code className="rounded-md bg-cosci-panel px-2 py-1">{id}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EvidenceTitle({
  evidence,
}: {
  evidence: NonNullable<HypothesisOutcome['referenced_evidence']>[number];
}) {
  const url = evidence.url ?? '';
  if (!/^https?:\/\//i.test(url)) return evidence.title;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="underline"
    >
      {evidence.title}
    </a>
  );
}

function OutcomeDetail({label, value}: {label: string; value: string}) {
  return (
    <div>
      <dt className="font-medium">{label}</dt>
      <dd className="whitespace-pre-wrap text-cosci-fg">{value}</dd>
    </div>
  );
}

function TextField({
  name,
  label,
  required = false,
  hint,
}: {
  name: string;
  label: string;
  required?: boolean;
  hint?: string;
}) {
  const isMultiline = name !== 'units';
  return (
    <label className="grid gap-1 text-sm font-medium">
      {label}
      {isMultiline ? (
        <textarea
          className={FIELD_CLASSES}
          name={name}
          rows={2}
          required={required}
          aria-describedby={hint ? `${name}-hint` : undefined}
        />
      ) : (
        <input className={FIELD_CLASSES} name={name} required={required} />
      )}
      {hint && (
        <span id={`${name}-hint`} className="font-normal text-cosci-muted">
          {hint}
        </span>
      )}
    </label>
  );
}
