import {
  useRef,
  type ButtonHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
  type RefObject,
} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {useDismiss} from '@/shared/hooks/use_dismiss';
import {joinClasses} from './cx';
import {presenceProps, usePresence} from './use_presence';

const SURFACE_CLASSES =
  'ui-motion-pop grid gap-[0.15rem] overflow-y-auto rounded-2xl border ' +
  'border-cosci-border bg-cosci-menu-bg p-[0.35rem] text-cosci-fg shadow-floating';

const ITEM_SELECTOR =
  '[role="menuitem"]:not([disabled]), [role="menuitemradio"]:not([disabled]), ' +
  '[role="menuitemcheckbox"]:not([disabled])';

// Arrow keys, Home and End move focus between items, as `role="menu"`
// promises.
function onMenuKeyDown(event: KeyboardEvent<HTMLElement>) {
  const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End'];
  if (!keys.includes(event.key)) return;
  const items = Array.from(
    event.currentTarget.querySelectorAll<HTMLElement>(ITEM_SELECTOR),
  );
  if (items.length === 0) return;
  event.preventDefault();
  const current = items.indexOf(document.activeElement as HTMLElement);
  const last = items.length - 1;
  const next = {
    ArrowDown: current < 0 || current === last ? 0 : current + 1,
    ArrowUp: current <= 0 ? last : current - 1,
    Home: 0,
    End: last,
  }[event.key as 'ArrowDown' | 'ArrowUp' | 'Home' | 'End'];
  items[next].focus();
}

interface MenuProps {
  open: boolean;
  onClose: () => void;
  label: string;
  // Pointer presses inside these (the trigger) do not count as outside.
  anchorRefs: RefObject<HTMLElement | null>[];
  // Position, size, stacking and transform origin only.
  layoutClassName: string;
  menuRef?: RefObject<HTMLDivElement | null>;
  children: ReactNode;
}

export function Menu({
  open,
  onClose,
  label,
  anchorRefs,
  layoutClassName,
  menuRef,
  children,
}: MenuProps) {
  const {mounted, state} = usePresence(open);
  const ownRef = useRef<HTMLDivElement>(null);
  const ref = menuRef ?? ownRef;
  useDismiss(open, onClose, [...anchorRefs, ref]);
  if (!mounted) return null;
  return (
    <div
      ref={ref}
      role="menu"
      aria-label={label}
      className={joinClasses(SURFACE_CLASSES, layoutClassName)}
      onKeyDown={onMenuKeyDown}
      {...presenceProps(state)}
    >
      {children}
    </div>
  );
}

export const MENU_ITEM_CLASSES =
  'flex min-h-[2.5rem] w-full cursor-pointer items-center gap-[0.72rem] ' +
  'rounded-xl border-0 bg-transparent px-[0.75rem] text-left font-[inherit] ' +
  'text-[0.875rem] text-cosci-fg no-underline hover:bg-cosci-menu-row-hover ' +
  'focus-visible:bg-cosci-menu-row-hover focus-visible:outline-2 ' +
  'focus-visible:-outline-offset-2 focus-visible:outline-th-ring ' +
  'disabled:cursor-default disabled:text-cosci-muted';

interface MenuItemProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  'className' | 'role'
> {
  kind?: 'item' | 'radio' | 'checkbox';
  checked?: boolean;
  icon?: IconName;
  ref?: Ref<HTMLButtonElement>;
}

const ROLE = {
  item: 'menuitem',
  radio: 'menuitemradio',
  checkbox: 'menuitemcheckbox',
} as const;

export function MenuItem({
  kind = 'item',
  checked,
  icon,
  children,
  type = 'button',
  ...rest
}: MenuItemProps) {
  return (
    <button
      type={type}
      role={ROLE[kind]}
      aria-checked={kind === 'item' ? undefined : Boolean(checked)}
      className={MENU_ITEM_CLASSES}
      {...rest}
    >
      {icon && (
        <Icon
          aria-hidden="true"
          className="flex-none text-[1.15rem] text-cosci-menu-icon"
          name={icon}
        />
      )}
      {children}
    </button>
  );
}
