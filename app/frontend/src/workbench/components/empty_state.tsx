import type {ReactNode} from 'react';

// The border/text tones are the named th-* utilities rather than inline
// `var(--md-sys-color-*)` styles: those tokens are declared as aliases of the
// very same MD3 variables (see theme_tokens.css), so they still read from the
// live runtime theme, and DESIGN.md keeps arbitrary token references out of
// components.
const BASE_CLASS =
  'rounded border border-th-border p-6 text-sm text-center text-th-muted-fg';

/**
 * Renders the shared bordered empty-state placeholder used by the run tabs.
 *
 * @param props The placeholder content and an optional extra className
 *   appended to the base classes.
 */
export function EmptyState({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className ? `${BASE_CLASS} ${className}` : BASE_CLASS}>
      {children}
    </div>
  );
}
