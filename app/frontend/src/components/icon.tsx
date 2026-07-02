import type {ReactNode, SVGProps} from 'react';

export type IconName =
  | 'add'
  | 'arrow_back'
  | 'arrow_forward'
  | 'article'
  | 'check_circle'
  | 'close'
  | 'computer'
  | 'content_copy'
  | 'dark_mode'
  | 'database'
  | 'download'
  | 'edit'
  | 'edit_square'
  | 'emoji_events'
  | 'emoji_objects'
  | 'expand_less'
  | 'expand_more'
  | 'format_list_numbered'
  | 'history'
  | 'light_mode'
  | 'menu'
  | 'menu_book'
  | 'open_in_new'
  | 'refresh'
  | 'search'
  | 'send'
  | 'settings'
  | 'shield'
  | 'stars'
  | 'view_list'
  | 'warning';

type IconProps = Omit<SVGProps<SVGSVGElement>, 'children' | 'name'> & {
  name: IconName;
};

const ICON_PATHS: Record<IconName, ReactNode> = {
  add: <path d="M12 5v14M5 12h14" />,
  arrow_back: <path d="M19 12H5m7-7-7 7 7 7" />,
  arrow_forward: <path d="M5 12h14m-7-7 7 7-7 7" />,
  article: (
    <>
      <path d="M7 3h7l4 4v14H7z" />
      <path d="M14 3v5h4M9 12h6M9 16h6M9 8h2" />
    </>
  ),
  check_circle: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 12.5 2.2 2.2 4.8-5.1" />
    </>
  ),
  close: <path d="m6 6 12 12M18 6 6 18" />,
  computer: (
    <>
      <rect x="4" y="5" width="16" height="11" rx="1.5" />
      <path d="M9 20h6M12 16v4" />
    </>
  ),
  content_copy: (
    <>
      <rect x="8" y="8" width="11" height="13" rx="1.5" />
      <path d="M5 16V5.5C5 4.7 5.7 4 6.5 4H15" />
    </>
  ),
  dark_mode: <path d="M20 14.5A8 8 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />,
  database: (
    <>
      <ellipse cx="12" cy="5.5" rx="7" ry="3" />
      <path d="M5 5.5v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
      <path d="M5 11.5v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
    </>
  ),
  download: <path d="M12 4v10m0 0 4-4m-4 4-4-4M5 20h14" />,
  edit: (
    <>
      <path d="M4 20h4l11-11-4-4L4 16z" />
      <path d="m13.5 6.5 4 4" />
    </>
  ),
  edit_square: (
    <>
      <path d="M12 5H6.5A2.5 2.5 0 0 0 4 7.5v10A2.5 2.5 0 0 0 6.5 20h10A2.5 2.5 0 0 0 19 17.5V12" />
      <path d="M14 4.5 19.5 10 11 18H7v-4z" />
    </>
  ),
  emoji_events: (
    <>
      <path d="M8 4h8v4a4 4 0 0 1-8 0z" />
      <path d="M8 6H5a3 3 0 0 0 3 3M16 6h3a3 3 0 0 1-3 3M12 12v4M9 20h6M10 16h4" />
    </>
  ),
  emoji_objects: (
    <>
      <path d="M9 18h6M10 21h4" />
      <path d="M8.5 14.5a5.5 5.5 0 1 1 7 0c-.9.7-1.5 1.6-1.5 2.5h-4c0-.9-.6-1.8-1.5-2.5Z" />
    </>
  ),
  expand_less: <path d="m6 15 6-6 6 6" />,
  expand_more: <path d="m6 9 6 6 6-6" />,
  format_list_numbered: (
    <>
      <path d="M10 6h10M10 12h10M10 18h10" />
      <path d="M4 5h1v3M4 8h2M4 11.5h2L4 14h2M4 17h2v3H4" />
    </>
  ),
  history: (
    <>
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v5h5M12 7v6l4 2" />
    </>
  ),
  light_mode: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  menu_book: (
    <>
      <path d="M4 5.5A3.5 3.5 0 0 1 7.5 2H12v17H7.5A3.5 3.5 0 0 0 4 22z" />
      <path d="M20 5.5A3.5 3.5 0 0 0 16.5 2H12v17h4.5A3.5 3.5 0 0 1 20 22z" />
    </>
  ),
  open_in_new: (
    <path d="M14 4h6v6M20 4l-9 9M19 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-12A1.5 1.5 0 0 1 4 18.5v-12A1.5 1.5 0 0 1 5.5 5H10" />
  ),
  refresh: (
    <path d="M20 6v5h-5M4 18v-5h5M18.5 9A7 7 0 0 0 6 7M5.5 15A7 7 0 0 0 18 17" />
  ),
  search: (
    <path d="m20 20-4.5-4.5M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" />
  ),
  send: <path d="M4 4 21 12 4 20l3-8zM7 12h14" />,
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19 13.5a7.8 7.8 0 0 0 0-3l2-1.5-2-3.4-2.4 1a8.5 8.5 0 0 0-2.6-1.5L13.7 2h-3.4l-.3 3.1a8.5 8.5 0 0 0-2.6 1.5l-2.4-1-2 3.4 2 1.5a7.8 7.8 0 0 0 0 3L3 15l2 3.4 2.4-1a8.5 8.5 0 0 0 2.6 1.5l.3 3.1h3.4l.3-3.1a8.5 8.5 0 0 0 2.6-1.5l2.4 1 2-3.4z" />
    </>
  ),
  shield: <path d="M12 3 5 6v5c0 4.8 3 8.2 7 10 4-1.8 7-5.2 7-10V6z" />,
  stars: (
    <>
      <path d="m12 3 1.8 5.1L19 10l-5.2 1.9L12 17l-1.8-5.1L5 10l5.2-1.9z" />
      <path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8zM5 3l.7 1.8L7.5 5.5l-1.8.7L5 8l-.7-1.8-1.8-.7 1.8-.7z" />
    </>
  ),
  view_list: (
    <path d="M4 6h3v3H4zM10 6h10M4 11h3v3H4zM10 11h10M4 16h3v3H4zM10 16h10" />
  ),
  warning: (
    <>
      <path d="M12 3 2.8 20h18.4z" />
      <path d="M12 9v5M12 17h.01" />
    </>
  ),
};

export function Icon({name, className, ...props}: IconProps) {
  return (
    <svg
      aria-hidden={props['aria-hidden'] ?? true}
      className={className}
      fill="none"
      focusable="false"
      height="1em"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
      viewBox="0 0 24 24"
      width="1em"
      {...props}
    >
      {ICON_PATHS[name]}
    </svg>
  );
}
