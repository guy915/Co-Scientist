import type {ReactNode} from 'react';

const BASE_CLASS = 'rounded border p-6 text-sm text-center';

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
    <div
      className={className ? `${BASE_CLASS} ${className}` : BASE_CLASS}
      style={{
        borderColor: 'var(--md-sys-color-outline-variant)',
        color: 'var(--md-sys-color-on-surface-variant)',
      }}
    >
      {children}
    </div>
  );
}
