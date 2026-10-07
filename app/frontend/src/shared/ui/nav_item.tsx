import type {MouseEventHandler} from 'react';
import {Link, type LinkProps} from 'react-router-dom';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses} from './cx';
import {tooltipClassNames} from './tooltip';

// The pressed colour stays in shell_surface.css (`ucs-nav-item`): Tailwind
// sorts an arbitrary :hover after :active, so a utility could not let pressed
// beat hover.
const ITEM_CLASSES =
  'ucs-nav-item grid size-[2.5rem] min-h-[2.5rem] min-w-[2.5rem] cursor-pointer place-items-center [border:0] rounded-full bg-transparent p-0 text-cosci-shell-icon no-underline ' +
  '[&:hover]:bg-cosci-shell-hover-bg [&:hover]:text-cosci-fg focus-visible:bg-cosci-shell-hover-bg focus-visible:text-cosci-fg ' +
  '[@media(max-width:700px)]:h-[2.75rem] [@media(max-width:700px)]:min-h-[2.75rem] [@media(max-width:700px)]:w-full ' +
  '[@media(max-width:700px)]:grid-cols-[1.5rem_minmax(0,1fr)] [@media(max-width:700px)]:[justify-items:start] [@media(max-width:700px)]:gap-x-[0.72rem] ' +
  '[@media(max-width:700px)]:px-[0.75rem] [@media(max-width:700px)]:text-left';

const ITEM_OPEN_CLASSES =
  'min-[701px]:h-[2.45rem] min-[701px]:min-h-[2.45rem] min-[701px]:w-full min-[701px]:grid-cols-[1.5rem_minmax(0,1fr)] ' +
  'min-[701px]:[justify-content:stretch] min-[701px]:[justify-items:start] min-[701px]:gap-x-[0.72rem] min-[701px]:px-[0.75rem] ' +
  'min-[701px]:text-left min-[701px]:leading-none';

const ITEM_COLLAPSED_CLASSES =
  'grid-cols-[1fr] justify-self-center min-[701px]:h-[2.45rem] min-[701px]:min-h-[2.45rem]';

const LABEL_CLASSES =
  'text-[0.875rem] font-medium tracking-[0.01em] whitespace-nowrap starting:opacity-0 ' +
  '[transition:opacity_var(--motion-duration-medium)_var(--motion-ease-standard),max-width_var(--motion-duration-long)_var(--motion-ease-standard)]';

// display:none, not visibility:hidden, which would keep a grid row and shift
// the icon. Width and overflow persist on phones, where labels show.
const LABEL_COLLAPSED_CLASSES =
  'hidden invisible w-0 max-w-0 overflow-hidden opacity-0 ' +
  '[@media(max-width:700px)]:block [@media(max-width:700px)]:max-w-none [@media(max-width:700px)]:opacity-100 [@media(max-width:700px)]:[visibility:inherit]';

const ICON_CLASSES =
  'grid size-[1.5rem] min-h-[1.5rem] min-w-[1.5rem] place-items-center justify-self-center text-[1.25rem] leading-none';

interface NavItemStyle {
  icon: IconName;
  label: string;
  // An open rail (and the phone drawer) shows labels; a collapsed rail shows
  // only the round icon with the label as its tooltip.
  open: boolean;
  layoutClassName?: string;
}

function itemClasses({open, layoutClassName}: NavItemStyle): string {
  return tooltipClassNames({
    className: joinClasses(
      ITEM_CLASSES,
      open ? ITEM_OPEN_CLASSES : ITEM_COLLAPSED_CLASSES,
      layoutClassName,
    ),
    placement: 'right',
  });
}

function NavItemContent({icon, label, open}: NavItemStyle) {
  return (
    <>
      <Icon aria-hidden="true" className={ICON_CLASSES} name={icon} />
      <span
        className={joinClasses(LABEL_CLASSES, !open && LABEL_COLLAPSED_CLASSES)}
      >
        {label}
      </span>
    </>
  );
}

// A rail destination that acts in place (toggle the rail, open a menu).
export function NavItemButton({
  expanded,
  controls,
  onClick,
  ...style
}: NavItemStyle & {
  expanded?: boolean;
  controls?: string;
  onClick: MouseEventHandler<HTMLButtonElement>;
}) {
  return (
    <button
      type="button"
      className={itemClasses(style)}
      aria-label={style.label}
      data-tooltip={style.label}
      aria-expanded={expanded}
      aria-controls={controls}
      onClick={onClick}
    >
      <NavItemContent {...style} />
    </button>
  );
}

// A rail destination that navigates.
export function NavItemLink({
  icon,
  label,
  open,
  layoutClassName,
  ...rest
}: NavItemStyle & Omit<LinkProps, 'className' | 'children'>) {
  const style = {icon, label, open, layoutClassName};
  return (
    <Link
      {...rest}
      className={itemClasses(style)}
      aria-label={label}
      data-tooltip={label}
    >
      <NavItemContent {...style} />
    </Link>
  );
}
