import type {
  InputHTMLAttributes,
  ReactNode,
  Ref,
  TextareaHTMLAttributes,
} from 'react';
import {joinClasses} from './cx';

export type FieldVariant = 'outlined' | 'bare';

// `bare` fields sit inside a surface that already draws the box (the
// composer, the bubble editor); that surface owns their focus treatment.
const VARIANT_CLASSES: Record<FieldVariant, string> = {
  outlined:
    'rounded-xl border border-field-border bg-transparent px-3.5 ' +
    'py-2.5 text-[0.9rem] text-cosci-fg focus-visible:border-field-focus ' +
    'focus-visible:outline-1 focus-visible:outline-offset-0 ' +
    'focus-visible:outline-field-focus disabled:cursor-default disabled:opacity-60',
  bare: 'border-0 bg-transparent p-0 text-cosci-fg outline-none',
};

export function fieldClasses(variant: FieldVariant = 'outlined'): string {
  return joinClasses(
    'w-full font-[inherit] placeholder:text-field-placeholder',
    VARIANT_CLASSES[variant],
  );
}

interface Shared {
  variant?: FieldVariant;
  layoutClassName?: string;
}

// A trailing action (send, clear) sits inside the field's box, so it never
// needs a row of its own.
export function TextField({
  variant,
  layoutClassName,
  trailing,
  ...rest
}: Shared &
  Omit<InputHTMLAttributes<HTMLInputElement>, 'className'> & {
    ref?: Ref<HTMLInputElement>;
    trailing?: ReactNode;
  }) {
  if (!trailing) {
    return (
      <input
        className={joinClasses(fieldClasses(variant), layoutClassName)}
        {...rest}
      />
    );
  }
  return (
    <div
      className={joinClasses(
        'relative flex min-w-0 items-center',
        layoutClassName,
      )}
    >
      <input
        className={joinClasses(fieldClasses(variant), 'pr-11')}
        {...rest}
      />
      <span className="absolute right-1 flex">{trailing}</span>
    </div>
  );
}

export function TextArea({
  variant,
  layoutClassName,
  ...rest
}: Shared &
  Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'className'> & {
    ref?: Ref<HTMLTextAreaElement>;
  }) {
  return (
    <textarea
      className={joinClasses(fieldClasses(variant), layoutClassName)}
      {...rest}
    />
  );
}
