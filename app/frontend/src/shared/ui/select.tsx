import {
  type CSSProperties,
  type RefObject,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import {Menu, MenuItem, SelectTrigger} from './menu';

const MENU_GAP_PX = 6;
const MENU_EDGE_PX = 16;

// Fixed menus escape scroll clipping, but transformed ancestors change their
// origin; measure and subtract that origin instead of assuming the viewport.
export function useAnchoredMenu(
  open: boolean,
  anchor: RefObject<HTMLDivElement | null>,
  align: 'start' | 'end' = 'start',
) {
  const menu = useRef<HTMLDivElement>(null);
  const [style, setStyle] = useState<CSSProperties>({});
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const el = menu.current;
      const trigger = anchor.current;
      if (!el || !trigger) return;
      el.style.top = '0px';
      el.style.left = '0px';
      el.style.maxHeight = '';
      const box = trigger.getBoundingClientRect();
      el.style.minWidth = `${box.width}px`;
      // The menu may be mid scale-in (origin top centre). Offset sizes ignore
      // the scale, and the measured left edge is shifted by half the shrink.
      const rect = el.getBoundingClientRect();
      const width = el.offsetWidth;
      const origin = {
        top: rect.top,
        left: rect.left - (width - rect.width) / 2,
        height: el.offsetHeight,
      };
      const left = align === 'end' ? box.right - width : box.left;
      // A long menu flips above its trigger when that side has more room, and
      // scrolls rather than running off the window.
      const below =
        window.innerHeight - box.bottom - MENU_GAP_PX - MENU_EDGE_PX;
      const above = box.top - MENU_GAP_PX - MENU_EDGE_PX;
      const up = origin.height > below && above > below;
      const room = Math.max(up ? above : below, 0);
      const top = up
        ? box.top - MENU_GAP_PX - Math.min(origin.height, room)
        : box.bottom + MENU_GAP_PX;
      const next = {
        top: top - origin.top,
        left: left - origin.left,
        minWidth: box.width,
        maxHeight: room,
      };
      el.style.top = `${next.top}px`;
      el.style.left = `${next.left}px`;
      el.style.maxHeight = `${room}px`;
      setStyle(next);
    }
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open, anchor, align]);
  return {menuRef: menu, menuStyle: style};
}

function groupOptions<T extends string>(
  options: readonly T[],
  groupOf?: (option: T) => string,
): {label: string | null; items: T[]}[] {
  if (!groupOf) return [{label: null, items: [...options]}];
  const sections: {label: string | null; items: T[]}[] = [];
  for (const option of options) {
    const label = groupOf(option);
    const last = sections[sections.length - 1];
    if (last?.label === label) last.items.push(option);
    else sections.push({label, items: [option]});
  }
  return sections;
}

// Real menu buttons preserve Tab/Enter behavior; selecting the current choice
// only dismisses the menu.
export function Select<T extends string>({
  value,
  options,
  optionLabel,
  optionNote,
  groupOf,
  name,
  triggerId,
  labelId,
  disabled = false,
  truncate = false,
  align = 'start',
  onChange,
}: {
  value: T;
  options: readonly T[];
  optionLabel: (option: T) => string;
  // Small trailing text, and headings over consecutive options sharing a group.
  optionNote?: (option: T) => string | null;
  groupOf?: (option: T) => string;
  name: string;
  triggerId: string;
  labelId: string;
  disabled?: boolean;
  truncate?: boolean;
  align?: 'start' | 'end';
  onChange: (option: T) => void;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const {menuRef, menuStyle} = useAnchoredMenu(open, container, align);

  return (
    <div
      // An auto track grows to the label's unwrapped width, so a long model id
      // pushed the trigger past the panel instead of ellipsizing.
      className="relative grid w-full grid-cols-[minmax(0,1fr)]"
      ref={container}
    >
      <SelectTrigger
        id={triggerId}
        open={open}
        aria-labelledby={`${labelId} ${triggerId}`}
        disabled={disabled}
        onClick={() => setOpen(current => !current)}
      >
        <span className={truncate ? 'truncate' : undefined}>
          {optionLabel(value)}
        </span>
      </SelectTrigger>
      <Menu
        open={open && !disabled}
        onClose={() => setOpen(false)}
        label={name}
        anchorRefs={[container]}
        menuRef={menuRef}
        style={menuStyle}
        // Absolute menus clip inside the scrolling Settings panel; fixed
        // anchored menus may escape its edges.
        layoutClassName="fixed top-0 left-0 z-40 w-max min-w-full origin-top"
      >
        {groupOptions(options, groupOf).map(section => (
          <div
            key={section.label ?? ''}
            // Options must stretch like direct menu children so highlights
            // span the row.
            className="grid"
            role={section.label ? 'group' : undefined}
            aria-label={section.label ?? undefined}
          >
            {section.label && (
              <div
                className="px-3 pt-1.5 pb-0.5 text-[0.75rem] text-cosci-muted"
                aria-hidden="true"
              >
                {section.label}
              </div>
            )}
            {section.items.map(option => (
              <MenuItem
                key={option}
                kind="radio"
                checked={option === value}
                indicator
                onClick={() => {
                  setOpen(false);
                  if (option !== value) onChange(option);
                }}
              >
                <span>{optionLabel(option)}</span>
                {optionNote?.(option) && (
                  <span className="ml-auto text-[0.75rem] text-cosci-muted">
                    {optionNote(option)}
                  </span>
                )}
              </MenuItem>
            ))}
          </div>
        ))}
      </Menu>
    </div>
  );
}
