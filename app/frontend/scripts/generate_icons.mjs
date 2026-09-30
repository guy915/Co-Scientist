// Generates src/components/icon.tsx from authentic Material Symbols Rounded
// glyphs (weight 400) shipped by @material-symbols/svg-400. Rounded matches
// the Google Symbols ROND-100 axis the live Gemini Enterprise product renders
// its icons with (measured July 2026).
//
// The glyph outlines are inlined as SVG paths so the icon set stays
// tree-shakeable, prerender-safe, and free of font FOUT while remaining
// pixel-identical to Google's Material Symbols.
//
// To add an icon: add a `publicName: 'material-symbols-file-stem'` entry to
// ICONS below, then run `node scripts/generate_icons.mjs`.

import {readFileSync, writeFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(
  HERE,
  '../node_modules/@material-symbols/svg-400/rounded',
);
const DEST = resolve(HERE, '../src/components/icon.tsx');

// Public icon name -> Material Symbols glyph file stem. Same name unless the
// current Material Symbols set renamed the glyph.
const ICONS = {
  // Org-chart glyph -- the landing page's Supervisor agent card.
  account_tree: 'account_tree',
  add: 'add',
  arrow_back: 'arrow_back',
  arrow_forward: 'arrow_forward',
  article: 'article',
  assignment: 'assignment',
  check: 'check',
  check_circle: 'check_circle',
  // Chessboard glyph — the reference's "Playing tournament" progress step.
  chess: 'chess',
  close: 'close',
  computer: 'computer',
  content_copy: 'content_copy',
  dark_mode: 'dark_mode',
  database: 'database',
  // Trash-with-X glyph -- the run titlebar's permanent-delete action.
  delete_forever: 'delete_forever',
  download: 'download',
  edit: 'edit',
  edit_square: 'edit_square',
  emoji_events: 'trophy',
  // Shield-with-a-keyhole. The reference product renders the Google-internal
  // 'android_security_privacy_safe' ligature (not in the public set); of the
  // public Material Symbols, 'encrypted' is the true shield-with-keyhole
  // (plain 'shield' is an empty shield, 'security' is quartered).
  encrypted: 'encrypted',
  expand_less: 'keyboard_arrow_up',
  expand_more: 'keyboard_arrow_down',
  format_list_numbered: 'format_list_numbered',
  // Two overlapping speech bubbles — the "Chat" side of the session switch,
  // which pairs a conversation with the results it produced. Deliberately not
  // the single 'chat' bubble, which reads as one message rather than a
  // running transcript.
  forum: 'forum',
  // Double helix -- the landing page's Evolution agent card.
  genetics: 'genetics',
  // Question-mark-in-a-circle — the reference settings menu's "Get help" row.
  help: 'help',
  // The recents clock-rewind glyph (clock face + counterclockwise arrow), not
  // the plain 'schedule' clock.
  history: 'history',
  // Overlapping circles -- the landing page's Proximity agent card.
  join: 'join',
  // Podium bars -- the landing page's Ranking agent card.
  leaderboard: 'leaderboard',
  light_mode: 'light_mode',
  // The plain outline light bulb (bulb body + base bars, no rays) the Idea
  // Generation product renders in its agent glyph — not 'emoji_objects', which
  // adds a filament and radiating rays.
  lightbulb: 'lightbulb',
  // Clipboard with a lab flask — the "Results" side of the session switch.
  // The report tabs already spend 'summarize' on Research Overview, so the
  // switch needs a glyph that names the whole report rather than one tab.
  lab_profile: 'lab_profile',
  menu: 'menu',
  menu_book: 'menu_book',
  // Outlined brain — the settings menu's "Model" row. Reads as model/AI and
  // matches the airy outlined set.
  neurology: 'neurology',
  open_in_new: 'open_in_new',
  // Painter's palette — the glyph the reference settings menu renders for
  // "Appearance" (an <md-icon>palette</md-icon> ligature in the 2026-06
  // gemini-enterprise capture, since deleted from references/).
  palette: 'palette',
  // The landing page's human-review safety card.
  person: 'person',
  // Shield with a magnifier -- the landing page's goal-screening card.
  policy: 'policy',
  // "Generating ideas" progress step — a speech bubble with a pencil.
  rate_review: 'rate_review',
  refresh: 'refresh',
  // Erlenmeyer flask — the "Lab papers" (SBI/UCD corpus) connector row.
  science: 'science',
  // "Reviewing ideas" progress step — a starred review badge.
  reviews: 'reviews',
  search: 'search',
  send: 'send-fill',
  settings: 'settings',
  // Share-node glyph — the goal-report titlebar's share-report action.
  share: 'share',
  stars: 'stars',
  // Filled square — the composer's Stop control while a turn is in flight,
  // matching the send glyph's filled treatment.
  stop: 'stop-fill',
  summarize: 'summarize',
  // Shield with a check -- the landing page's idea-screening card.
  verified_user: 'verified_user',
  warning: 'warning',
};

function extractPaths(svg) {
  const ds = [...svg.matchAll(/<path[^>]*\sd="([^"]+)"/g)].map(m => m[1]);
  if (!ds.length) throw new Error('no path found');
  return ds;
}

const names = Object.keys(ICONS).sort();
const entries = names.map(name => {
  const svg = readFileSync(`${SRC}/${ICONS[name]}.svg`, 'utf8');
  const body = extractPaths(svg)
    .map(d => `<path d="${d}" />`)
    .join('');
  return {name, body};
});

const union = names.map(n => `  | '${n}'`).join('\n');
const map = entries.map(e => `  ${e.name}: <>${e.body}</>,`).join('\n');

const out = `import type {ReactNode, SVGProps} from 'react';

// GENERATED by scripts/generate_icons.mjs from @material-symbols/svg-400.
// Do not edit by hand; add icons in the generator and re-run it.
//
// Authentic Material Symbols Rounded glyphs (weight 400) — the public cut of
// Google Symbols ROND 100, which the live Gemini Enterprise product uses —
// rendered as inline SVG so the set is tree-shakeable, prerender-safe, and
// free of font FOUT. Glyphs use the Material Symbols 0 -960 960 960 grid and
// are filled paths (never stroked).

export type IconName =
${union};

type IconProps = Omit<SVGProps<SVGSVGElement>, 'children' | 'name'> & {
  name: IconName;
};

const ICON_PATHS: Record<IconName, ReactNode> = {
${map}
};

export function Icon({name, className, ...props}: IconProps) {
  return (
    <svg
      aria-hidden={props['aria-hidden'] ?? true}
      className={className}
      fill="currentColor"
      focusable="false"
      height="1em"
      viewBox="0 -960 960 960"
      width="1em"
      {...props}
    >
      {ICON_PATHS[name]}
    </svg>
  );
}
`;

writeFileSync(DEST, out);
console.log(`Wrote ${names.length} authentic Material Symbols to ${DEST}`);
