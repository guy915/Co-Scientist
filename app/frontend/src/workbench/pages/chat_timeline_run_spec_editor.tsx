// In-place field editing for the plan card. Split out of
// chat_timeline_run_spec_card.tsx, which sat at the repo's 500-line
// ceiling; SpecRow/SpecList/SpecSummary moved here with the new editable
// form because the form swaps in for exactly the summary they render, and
// nothing outside chat_timeline_run_spec_card.tsx imported them, so there
// is nothing left for the parent to re-export.
//
// The form this opens is what the card's header pencil ("Edit plan", see
// PlanHeading) now shows: a scientist who already knows the exact wording
// they want types it here rather than prompting for it. The pencil used to
// re-stage the spec as a draft and hand editing back to the conversation
// instead, which is what typing another message already does -- so the
// header kept the affordance the composer cannot give, and the trigger
// this form used to carry inside the plan box went away with it.

import {type ReactNode, useId, useState} from 'react';
import {editInterviewFields} from '@/api/runs';
import {Icon} from '@/components/icon';
import {
  type EditedSpecFields,
  type InferredRunSpec,
  applyEditedInterviewFields,
  buildInterviewFieldsPayload,
} from '../run_spec';
import {
  SETUP_ACTIONS_CLASSES,
  SETUP_PRIMARY_BUTTON_CLASSES,
  SETUP_SECONDARY_BUTTON_CLASSES,
  SPEC_DETAIL_CLASSES,
  SPEC_EDIT_ADD_BUTTON_CLASSES,
  SPEC_EDIT_ADD_ICON_CLASSES,
  SPEC_EDIT_ERROR_CLASSES,
  SPEC_EDIT_FIELD_CLASSES,
  SPEC_EDIT_FIELDSET_CLASSES,
  SPEC_EDIT_FORM_CLASSES,
  SPEC_EDIT_INPUT_CLASSES,
  SPEC_EDIT_LABEL_CLASSES,
  SPEC_EDIT_LEGEND_CLASSES,
  SPEC_EDIT_LIST_ROW_CLASSES,
  SPEC_EDIT_REMOVE_BUTTON_CLASSES,
  SPEC_EDIT_REMOVE_ICON_CLASSES,
  SPEC_EDIT_TEXTAREA_CLASSES,
  SPEC_GRID_CLASSES,
  SPEC_LIST_CLASSES,
  SPEC_ROW_CLASSES,
  SPEC_TERM_CLASSES,
} from './chat_setup_classes';

// One term/detail row in the read-only spec definition list (dt/dd pair).
function SpecRow({label, children}: {label: string; children: ReactNode}) {
  return (
    <div className={SPEC_ROW_CLASSES}>
      <dt className={SPEC_TERM_CLASSES}>{label}:</dt>
      <dd className={SPEC_DETAIL_CLASSES}>{children}</dd>
    </div>
  );
}

// A read-only spec row whose value is a bulleted list (Focus Area/
// Preferences) rather than plain text (Research Challenge/Title).
function SpecList({label, values}: {label: string; values: string[]}) {
  return (
    <SpecRow label={label}>
      <ul className={SPEC_LIST_CLASSES}>
        {values.map(value => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </SpecRow>
  );
}

// The interview fields plus any extra criteria stored on the run setup.
function SpecSummary({spec}: {spec: InferredRunSpec}) {
  return (
    <dl className={SPEC_GRID_CLASSES}>
      <SpecRow label="Research Challenge">{spec.goal}</SpecRow>
      <SpecList label="Focus Area" values={spec.attributes} />
      <SpecList label="Preferences" values={spec.requirements} />
      {spec.criteria.length > 0 && (
        <SpecList label="Criteria" values={spec.criteria} />
      )}
      <SpecRow label="Title">{spec.title || 'Optional'}</SpecRow>
    </dl>
  );
}

// One editable list entry: a plain text input paired with a remove button.
// The row carries no visible per-item label of its own, so both the input
// and the remove button name the field (and, for remove, the value) through
// aria-label instead.
function EditableListRow({
  label,
  value,
  index,
  onChange,
  onRemove,
}: {
  label: string;
  value: string;
  index: number;
  onChange: (value: string) => void;
  onRemove: () => void;
}) {
  const removeLabel = value.trim()
    ? `Remove "${value}" from ${label}`
    : `Remove empty ${label} entry`;
  return (
    <div className={SPEC_EDIT_LIST_ROW_CLASSES}>
      <input
        type="text"
        className={SPEC_EDIT_INPUT_CLASSES}
        aria-label={`${label} item ${index + 1}`}
        value={value}
        onChange={e => onChange(e.target.value)}
      />
      <button
        type="button"
        className={SPEC_EDIT_REMOVE_BUTTON_CLASSES}
        aria-label={removeLabel}
        onClick={onRemove}
      >
        <Icon
          aria-hidden="true"
          name="close"
          className={SPEC_EDIT_REMOVE_ICON_CLASSES}
        />
      </button>
    </div>
  );
}

// One editable list (Focus Area or Preferences): a fieldset of entry rows
// plus an "Add" trigger that appends a blank row to fill in.
function EditableList({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  function updateAt(index: number, value: string) {
    onChange(values.map((entry, i) => (i === index ? value : entry)));
  }
  function removeAt(index: number) {
    onChange(values.filter((_, i) => i !== index));
  }
  return (
    <fieldset className={SPEC_EDIT_FIELDSET_CLASSES}>
      <legend className={SPEC_EDIT_LEGEND_CLASSES}>{label}</legend>
      {values.map((value, index) => (
        <EditableListRow
          // Index-keyed: rows are edited and removed by position, and this
          // list only ever grows/shrinks by one row at a time.
          key={index}
          label={label}
          value={value}
          index={index}
          onChange={v => updateAt(index, v)}
          onRemove={() => removeAt(index)}
        />
      ))}
      <button
        type="button"
        className={SPEC_EDIT_ADD_BUTTON_CLASSES}
        onClick={() => onChange([...values, ''])}
      >
        <Icon
          aria-hidden="true"
          name="add"
          className={SPEC_EDIT_ADD_ICON_CLASSES}
        />
        Add {label.toLowerCase()}
      </button>
    </fieldset>
  );
}

// Props for SpecFieldsForm, named at module level per the destructured prop
// signature otherwise pushing the component past the line cap.
interface SpecFieldsFormProps {
  values: EditedSpecFields;
  onChange: (patch: Partial<EditedSpecFields>) => void;
  onSave: () => void;
  onCancel: () => void;
  canSave: boolean;
  isSaving: boolean;
  error: string | null;
}

// The goal textarea, the two editable lists, and the title input -- the
// part of the form that edits values. Split from the Save/Cancel row below
// (SpecFieldsFormActions) to keep both under the repo's line cap.
function SpecFieldsFormFields({
  values,
  onChange,
}: Pick<SpecFieldsFormProps, 'values' | 'onChange'>) {
  const goalId = useId();
  const titleId = useId();
  return (
    <>
      <div className={SPEC_EDIT_FIELD_CLASSES}>
        <label htmlFor={goalId} className={SPEC_EDIT_LABEL_CLASSES}>
          Research Challenge
        </label>
        <textarea
          id={goalId}
          className={SPEC_EDIT_TEXTAREA_CLASSES}
          value={values.goal}
          onChange={e => onChange({goal: e.target.value})}
        />
      </div>
      <EditableList
        label="Focus Area"
        values={values.attributes}
        onChange={attributes => onChange({attributes})}
      />
      <EditableList
        label="Preferences"
        values={values.requirements}
        onChange={requirements => onChange({requirements})}
      />
      <div className={SPEC_EDIT_FIELD_CLASSES}>
        <label htmlFor={titleId} className={SPEC_EDIT_LABEL_CLASSES}>
          Title
        </label>
        <input
          id={titleId}
          type="text"
          className={SPEC_EDIT_INPUT_CLASSES}
          value={values.title}
          onChange={e => onChange({title: e.target.value})}
        />
      </div>
    </>
  );
}

// The form's error line plus its Save/Cancel row. A failed save leaves the
// form open (and shows why) so the scientist doesn't lose what they typed.
function SpecFieldsFormActions(
  props: Pick<
    SpecFieldsFormProps,
    'onSave' | 'onCancel' | 'canSave' | 'isSaving' | 'error'
  >,
) {
  const {onSave, onCancel, canSave, isSaving, error} = props;
  return (
    <>
      {error && (
        <p
          className={SPEC_EDIT_ERROR_CLASSES}
          style={{color: 'var(--md-sys-color-error)'}}
        >
          {error}
        </p>
      )}
      <div className={SETUP_ACTIONS_CLASSES}>
        <button
          type="button"
          className={SETUP_SECONDARY_BUTTON_CLASSES}
          onClick={onCancel}
          disabled={isSaving}
        >
          Cancel
        </button>
        <button
          type="button"
          className={SETUP_PRIMARY_BUTTON_CLASSES}
          onClick={onSave}
          disabled={!canSave || isSaving}
        >
          {isSaving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </>
  );
}

function SpecFieldsForm(props: SpecFieldsFormProps) {
  return (
    <div className={SPEC_EDIT_FORM_CLASSES}>
      <SpecFieldsFormFields values={props.values} onChange={props.onChange} />
      <SpecFieldsFormActions {...props} />
    </div>
  );
}

/** The plan card's field-editing state, as useSpecFieldsEditor returns it. */
export type SpecFieldsEditor = ReturnType<typeof useSpecFieldsEditor>;

function formValues(spec: InferredRunSpec): EditedSpecFields {
  return {
    goal: spec.goal,
    title: spec.title ?? '',
    attributes: [...spec.attributes],
    requirements: [...spec.requirements],
  };
}

// The editor's local state and its save round trip, pulled out of
// SpecFieldsSection so that component stays a thin render (the repo's
// convention of keeping logic in named functions rather than component
// closures -- see chat_session_handlers.ts's deps-bag handlers).
export function useSpecFieldsEditor(
  spec: InferredRunSpec,
  onFieldsChange: (patch: Partial<InferredRunSpec>) => void,
) {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<EditedSpecFields>(() =>
    formValues(spec),
  );
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!spec.interviewId) return;
    setIsSaving(true);
    setError(null);
    try {
      const interview = await editInterviewFields(
        spec.interviewId,
        buildInterviewFieldsPayload(values),
      );
      onFieldsChange(applyEditedInterviewFields(interview));
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save changes.');
    } finally {
      setIsSaving(false);
    }
  }

  return {
    editing,
    values,
    isSaving,
    error,
    canSave: values.goal.trim().length > 0,
    onValuesChange: (patch: Partial<EditedSpecFields>) =>
      setValues(current => ({...current, ...patch})),
    startEditing: () => {
      setValues(formValues(spec));
      setError(null);
      setEditing(true);
    },
    cancelEditing: () => setEditing(false),
    save: () => void save(),
  };
}

/**
 * Renders the plan card's four interview-derived fields: the read-only
 * summary, or the editable form once the header's "Edit plan" pencil has
 * opened it. Saving persists through `editInterviewFields` and reports the
 * server's own updated values back to `onFieldsChange` -- the server trims
 * list entries, so the card adopts what it returns rather than the
 * locally-typed values.
 *
 * The editor's state is owned by the card (see useSpecFieldsEditor), not by
 * this section: the control that opens it sits beside the "Research plan"
 * heading, outside the box these fields are in.
 */
export function SpecFieldsSection({
  spec,
  editor,
}: {
  spec: InferredRunSpec;
  editor: SpecFieldsEditor;
}) {
  if (!editor.editing) return <SpecSummary spec={spec} />;
  return (
    <SpecFieldsForm
      values={editor.values}
      onChange={editor.onValuesChange}
      onSave={editor.save}
      onCancel={editor.cancelEditing}
      canSave={editor.canSave}
      isSaving={editor.isSaving}
      error={editor.error}
    />
  );
}
