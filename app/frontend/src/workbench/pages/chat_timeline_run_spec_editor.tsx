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
} from '../classes';
const SPEC_EDIT_INPUT_CLASSES =
  'w-full rounded-[0.65rem] border border-cosci-composer-border bg-cosci-composer-bg px-[0.85rem] py-[0.6rem] text-base text-cosci-composer-text outline-none focus-visible:border-cosci-fg';
const SPEC_EDIT_FIELD_CLASSES = 'grid gap-[0.5rem]';
const SPEC_EDIT_LABEL_CLASSES = 'text-[1.18rem] font-bold text-cosci-fg';

function SpecRow({label, children}: {label: string; children: ReactNode}) {
  return (
    <div className="reference-spec-row block text-base">
      <dt className="mb-[0.85rem] text-[1.18rem] font-bold text-cosci-fg">
        {label}:
      </dt>
      <dd className="m-0 leading-[1.45] text-cosci-fg">{children}</dd>
    </div>
  );
}

function SpecList({label, values}: {label: string; values: string[]}) {
  return (
    <SpecRow label={label}>
      <ul className="reference-spec-list m-0 grid list-disc gap-[0.8rem] pl-[1.35rem]">
        {values.map(value => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </SpecRow>
  );
}

function SpecSummary({spec}: {spec: InferredRunSpec}) {
  return (
    <dl className="reference-setup-grid m-0 grid gap-[1.55rem]">
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

// Name unlabeled entry inputs and remove controls through aria-label.
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
    <div className="flex items-center gap-[0.5rem]">
      <input
        type="text"
        className={SPEC_EDIT_INPUT_CLASSES}
        aria-label={`${label} item ${index + 1}`}
        value={value}
        onChange={e => onChange(e.target.value)}
      />
      <button
        type="button"
        className="size-[2.1rem] shrink-0 grid cursor-pointer place-items-center rounded-full border-0 bg-transparent p-0 text-cosci-muted hover:bg-cosci-hover hover:text-cosci-fg focus-visible:bg-cosci-hover focus-visible:text-cosci-fg"
        aria-label={removeLabel}
        onClick={onRemove}
      >
        <Icon aria-hidden="true" name="close" className="text-[1.15rem]" />
      </button>
    </div>
  );
}

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
    <fieldset className="m-0 grid gap-[0.6rem] border-0 p-0">
      <legend className="text-[1.18rem] font-bold text-cosci-fg">
        {label}
      </legend>
      {values.map((value, index) => (
        <EditableListRow
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
        className="reference-spec-edit-add flex w-fit cursor-pointer items-center gap-[0.3rem] rounded-full border-0 bg-transparent px-[0.2rem] py-[0.3rem] text-[0.9rem] font-medium text-cosci-muted hover:text-cosci-fg focus-visible:text-cosci-fg"
        onClick={() => onChange([...values, ''])}
      >
        <Icon aria-hidden="true" name="add" className="text-[1.05rem]" />
        Add {label.toLowerCase()}
      </button>
    </fieldset>
  );
}

interface SpecFieldsFormProps {
  values: EditedSpecFields;
  onChange: (patch: Partial<EditedSpecFields>) => void;
  onSave: () => void;
  onCancel: () => void;
  canSave: boolean;
  isSaving: boolean;
  error: string | null;
}

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
          className="w-full rounded-[0.65rem] border border-cosci-composer-border bg-cosci-composer-bg px-[0.85rem] py-[0.6rem] text-base text-cosci-composer-text outline-none focus-visible:border-cosci-fg min-h-[6rem] resize-y leading-[1.45]"
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

// Keep failed saves open so the scientist does not lose their edits.
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
          className="m-0 text-[0.9rem]"
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
    <div className="reference-spec-edit-form grid gap-[1.15rem]">
      <SpecFieldsFormFields values={props.values} onChange={props.onChange} />
      <SpecFieldsFormActions {...props} />
    </div>
  );
}

export type SpecFieldsEditor = ReturnType<typeof useSpecFieldsEditor>;

function formValues(spec: InferredRunSpec): EditedSpecFields {
  return {
    goal: spec.goal,
    title: spec.title ?? '',
    attributes: [...spec.attributes],
    requirements: [...spec.requirements],
  };
}

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

// Adopt server-returned fields after saving because the server trims list
// entries.
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
