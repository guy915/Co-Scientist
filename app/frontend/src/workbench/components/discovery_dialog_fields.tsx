import type {DiscoveryDraft} from './discovery_draft';

// One labelled text input. The settings dialog's field classes, so this
// surface inherits its spacing and focus ring rather than growing a
// second set of form styles that drift from it.
function Field({
  label,
  value,
  onChange,
  hint,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  placeholder?: string;
}) {
  return (
    <label className="ucs-settings-field-label ucs-settings-field-label--spaced">
      {label}
      <input
        className="ucs-settings-field-input"
        value={value}
        placeholder={placeholder}
        onChange={event => onChange(event.target.value)}
      />
      {hint ? <p className="ucs-settings-field-hint">{hint}</p> : null}
    </label>
  );
}

/** How a draft's fields are updated: one key at a time. */
export type DraftChange = <K extends keyof DiscoveryDraft>(
  key: K,
  value: DiscoveryDraft[K],
) => void;

/** What the run optimizes, and how the program reports it. */
export function ObjectiveFields({
  draft,
  onChange,
}: {
  draft: DiscoveryDraft;
  onChange: DraftChange;
}) {
  return (
    <section className="ucs-settings-card">
      <h3 className="ucs-settings-card-title">What to optimize</h3>
      <p className="ucs-settings-card-copy">
        Your program writes a <code>metrics.json</code> file. Name the key the
        search should optimize, and which direction is better.
      </p>
      <Field
        label="Metric"
        value={draft.metric}
        onChange={value => onChange('metric', value)}
      />
      <label className="ucs-settings-field-label ucs-settings-field-label--spaced">
        Direction
        <select
          className="ucs-settings-field-input"
          value={draft.direction}
          onChange={event =>
            onChange(
              'direction',
              event.target.value as DiscoveryDraft['direction'],
            )
          }
        >
          <option value="maximize">Higher is better</option>
          <option value="minimize">Lower is better</option>
        </select>
      </label>
    </section>
  );
}

/** The program the run starts from, and the command that runs it. */
export function ProgramFields({
  draft,
  onChange,
}: {
  draft: DiscoveryDraft;
  onChange: DraftChange;
}) {
  return (
    <section className="ucs-settings-card">
      <h3 className="ucs-settings-card-title">The program</h3>
      <p className="ucs-settings-card-copy">
        The starting point the search improves on. It runs in a sandbox with no
        network access and can write only its own directory.
      </p>
      <Field
        label="File name"
        value={draft.filename}
        onChange={value => onChange('filename', value)}
      />
      <Field
        label="Command"
        value={draft.command}
        onChange={value => onChange('command', value)}
        hint="Split on spaces. No shell runs, so pipes and quotes are literal."
      />
      <label className="ucs-settings-field-label ucs-settings-field-label--spaced">
        Program
        <textarea
          className="ucs-settings-field-input font-mono"
          rows={12}
          value={draft.program}
          onChange={event => onChange('program', event.target.value)}
        />
      </label>
    </section>
  );
}

/** How long the search runs for. */
export function BudgetFields({
  draft,
  onChange,
}: {
  draft: DiscoveryDraft;
  onChange: DraftChange;
}) {
  return (
    <section className="ucs-settings-card">
      <h3 className="ucs-settings-card-title">How long to search</h3>
      <Field
        label="Generations"
        value={draft.generations}
        onChange={value => onChange('generations', value)}
      />
      <Field
        label="Variants per generation"
        value={draft.children}
        onChange={value => onChange('children', value)}
        hint="Each one is a model call and a sandboxed run."
      />
    </section>
  );
}
