import {useRef, type ReactNode} from 'react';
import {Link, type LinkProps} from 'react-router-dom';
import {Icon, type IconName} from '@/components/icon';
import {useSlidingIndicator} from '@/shared/hooks/use_sliding_indicator';
import {joinClasses} from './cx';

// One moving thumb owns the selected fill, so a change of selection slides
// instead of one background vanishing and another appearing.
function SlidingThumb({
  trackRef,
  selector,
  selected,
  className,
  children,
}: {
  trackRef: React.RefObject<HTMLElement | null>;
  selector: string;
  selected: string;
  className: string;
  children?: ReactNode;
}) {
  const box = useSlidingIndicator(trackRef, selector, selected);
  if (!box) return null;
  return (
    <span
      aria-hidden="true"
      data-animate={box.animate}
      className={joinClasses('ui-sliding-thumb', className)}
      style={{width: box.width, translate: `${box.left}px 0`}}
    >
      {children}
    </span>
  );
}

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: IconName;
}

// A pressed-button group for choosing one value in place (theme, tier). Links
// that change the route use TabNav instead.
export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  layoutClassName,
}: {
  label: string;
  options: readonly SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  layoutClassName?: string;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  return (
    <div
      ref={trackRef}
      role="group"
      aria-label={label}
      className={joinClasses(
        'relative grid auto-cols-fr grid-flow-col gap-[0.3rem] rounded-full border',
        'border-segmented-border bg-segmented-track p-[0.18rem]',
        layoutClassName,
      )}
    >
      <SlidingThumb
        trackRef={trackRef}
        selector='[aria-pressed="true"]'
        selected={value}
        className="absolute inset-y-[0.18rem] left-0 rounded-full bg-segmented-thumb"
      />
      {options.map(option => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className={joinClasses(
            'relative z-[1] inline-flex min-h-[2.6rem] cursor-pointer items-center',
            'justify-center gap-[0.45rem] rounded-full border-0 bg-transparent px-3',
            'font-[inherit] text-[0.875rem] font-semibold text-segmented-fg',
            'aria-[pressed=false]:hover:bg-segmented-hover',
            'aria-pressed:text-segmented-selected-fg focus-visible:outline-2',
            'focus-visible:outline-offset-2 focus-visible:outline-th-ring',
          )}
        >
          {option.icon && (
            <Icon
              aria-hidden="true"
              className="text-[1.1rem]"
              name={option.icon}
            />
          )}
          {option.label}
        </button>
      ))}
    </div>
  );
}

export type TabNavVariant = 'underline' | 'pill';

const TRACK_CLASSES: Record<TabNavVariant, string> = {
  underline:
    'relative grid grid-flow-col auto-cols-fr border-b border-cosci-border',
  pill: 'relative inline-grid grid-flow-col auto-cols-fr rounded-full bg-tab-pill-track',
};

const THUMB_CLASSES: Record<TabNavVariant, string> = {
  underline: 'absolute bottom-0 left-0 h-[0.18rem]',
  pill: 'absolute inset-y-0 left-0 rounded-full bg-tab-pill-thumb',
};

const LINK_CLASSES: Record<TabNavVariant, string> = {
  underline:
    'relative grid min-w-0 cursor-pointer content-center justify-items-center ' +
    'gap-[0.35rem] py-2 text-sm no-underline text-cosci-muted ' +
    'hover:text-cosci-fg aria-[current=page]:text-cosci-blue',
  pill:
    'relative z-[1] flex h-full min-w-0 items-center justify-center ' +
    'gap-[0.45rem] rounded-full px-[0.72rem] no-underline text-tab-pill-fg ' +
    'aria-[current=page]:text-tab-pill-selected-fg ' +
    'not-aria-[current=page]:hover:bg-tab-pill-hover',
};

export function tabLinkClasses(variant: TabNavVariant): string {
  return joinClasses(
    LINK_CLASSES[variant],
    'focus-visible:outline-2 focus-visible:-outline-offset-2 ' +
      'focus-visible:outline-th-ring',
  );
}

// Navigation between routes: real links with aria-current, which is what deep
// links and new tabs need; the indicator follows the current link.
export function TabNav({
  label,
  variant,
  current,
  layoutClassName,
  children,
}: {
  label: string;
  variant: TabNavVariant;
  // Changes whenever the current link changes, so the indicator re-measures.
  current: string;
  layoutClassName?: string;
  children: ReactNode;
}) {
  const trackRef = useRef<HTMLElement>(null);
  return (
    <nav
      ref={trackRef}
      aria-label={label}
      className={joinClasses(TRACK_CLASSES[variant], layoutClassName)}
    >
      <SlidingThumb
        trackRef={trackRef}
        selector='[aria-current="page"]'
        selected={current}
        className={THUMB_CLASSES[variant]}
      >
        {variant === 'underline' && (
          <span className="mx-[1.1rem] block h-full rounded-t-full bg-cosci-blue-strong" />
        )}
      </SlidingThumb>
      {children}
    </nav>
  );
}

export function TabNavLink({
  variant,
  current,
  className,
  ...rest
}: LinkProps & {variant: TabNavVariant; current: boolean}) {
  return (
    <Link
      {...rest}
      aria-current={current ? 'page' : undefined}
      className={joinClasses(tabLinkClasses(variant), className)}
    />
  );
}
