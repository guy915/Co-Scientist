const FIELD_CLASSES =
  'w-full rounded-md border border-cosci-border bg-cosci-bg px-3 py-2 ' +
  'text-sm text-cosci-fg focus-visible:outline-2 ' +
  'focus-visible:outline-cosci-accent';

export function TextField({
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
