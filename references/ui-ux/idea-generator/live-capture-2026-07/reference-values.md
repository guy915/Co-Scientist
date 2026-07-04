# Idea Generation (Gemini Enterprise) — live capture, July 2026

Measured from the running product at
`vertexaisearch.cloud.google.com/.../r/ideaforge/-` via DevTools computed
styles (shadow-DOM-piercing probe). Viewport 1600x869 @ dpr 1.8, light theme.
This is the pixel truth for the visual-fidelity pass; deliberate divergences
(green accent instead of purple, branding, composer options) are documented in
`docs/ui-fidelity.md` and stay as-is.

## Global

- Display font: `"Google Sans"` (greeting, brand). Body/UI font:
  `"Google Sans Text", "Google Sans", roboto, sans-serif`.
- Text colors: primary `rgb(31,31,31)` (#1f1f1f), secondary `rgb(68,71,70)`
  (#444746 = on-surface-variant).
- Icon font: `"Google Symbols"` (`--md-icon-font`).
- Focus ring: width 2px, outward offset -2px, duration 0ms.
- Menu container shape: 16px (`--md-menu-container-shape`).
- Scrollbar: track `#f1f3f4`, thumb `#bdc1c6`, thumb hover `#747775`.

## Home page

| Element | Values |
|---|---|
| Greeting ("Create a multi-agent innovation session") | Google Sans 45px/52px w400, #1f1f1f, margin-bottom 8px, width 550px |
| Agent chip label ("Idea Generation") | Google Sans Text 14px/24px w500, color `rgb(8,66,160)` (#0842a0 = on-primary-container), padding-left 10px, transition `opacity .125s ease` |
| Step circle (1/2/3) | 30x30, border-radius 50%, bg `rgb(197,151,255)` (#c597ff = purple70; ours: green equivalent), text `rgb(242,242,242)` 16px/24px w400, flex-centered, transition `background-color .3s ease-in-out` |
| Step title ("Getting started") | Google Sans Text 14px/20px w400, #444746 |
| Step body | Google Sans Text 14px/20px w400, **#1f1f1f** (body darker than title) |
| Step row container | `.overview-blocks.progress-container` flex, gap 16px, align center, justify space-between, width 760px |
| Step column | width 230px (titles+body), circles row y=364, titles y=408 (44px below circle top) |
| Suggestion card text | Google Sans Text 14px/20px w400 #1f1f1f, content box 218x40 |
| Composer placeholder ("Ask Idea Generation") | Google Sans Text 16px/24px w400, #444746 (ProseMirror placeholder) |
| Composer icon buttons (plus/send) | 40x40 flex-centered `button.icon-button.standard` |
| Recents header | Google Sans Text 16px/24px w500, #1f1f1f, margin-bottom 16px |

### Recents card (`.card`)

- Container: 298px wide, radius **12px**, padding **16px**, bg #fff,
  display flex (column) gap 8px.
- **Box-shadow: `rgba(0,0,0,0.15) 0 1px 2px 0, rgba(0,0,0,0.1) 0 2px 10px 0`**
  — the reference DOES use an elevation shadow on recents cards (not
  tonal-only).
- Top bar (date + total time chips): flex gap 6px, margin-bottom 8px.
- Chips (date / total-time): Google Sans Text **11px/16px w500, ls 0.1px**,
  padding **4px 8px**, radius **5px**, bg `rgb(240,244,249)` (#f0f4f9 =
  surface-container), text #1f1f1f.
- Winning chips ("Winning ideas", "Top score: N"): same recipe but bg
  `rgb(190,239,187)` (#beefbb = green90). Green in the ORIGINAL — keep.
- Winning-idea header row: flex gap 6px.
- Title: Google Sans Text 16px/24px w500 #1f1f1f.
- Winning ideas list `ol.winning-ideas`: margin `8px 0 0 16px`, items
  Google Sans Text **12px/16px w400 ls 0.1px** #1f1f1f, ~4px gap between
  items (li 32px high for 2-line).

### Top bar

- Brand "Gemini Enterprise": Google Sans 20px w500, ls -0.6px, #1f1f1f.
- "Plus" badge: Google Sans Text 12px/18px w500 ls 0.1px, #444746, border
  0.556px solid #444746, radius 8px, padding 0 8px, margin-left 8px.

### Nav rail

- `ucs-nav-panel` width 72px full-height.

## Palette (md-sys light, from computed custom props)

Core:
- primary `#0b57d0`, on-primary `#fff`, primary-container `#d3e3fd`,
  on-primary-container `#0842a0`
- secondary `#00639b`, secondary-container `#c2e7ff`, on-secondary-container `#004a77`
- tertiary `#146c2e`, tertiary-fixed `#c4eed0`
- error `#b3261e`, error-container `#f9dedc`
- background/surface `#fff`, surface-bright `#fff`
- surface-container-lowest `#fff`, -low `#f8fafd`, -container `#f0f4f9`,
  -high `#e9eef6`, -highest `#dde3ea`
- on-surface `#1f1f1f`, on-surface-variant `#444746`
- outline `#747775`, outline-variant `#c4c7c5`
- inverse-surface `#303030`, inverse-on-surface `#f2f2f2`, inverse-primary `#a8c7fa`
- surface-variant `#e1e3e1`, shadow `#000`, scrim `#000`

Ref-palette accents seen in use:
- purple70 `#c597ff` (step circles), purple90 `#eedcfe`, purple95 `#f7ecfe`,
  purple40 `#7438d2`, purple50 `#9254ea`
- green90 `#beefbb` (winning chips), green95 `#ddf8d8`, green98 `#f2fcef`,
  green600 `#1e8e3e`, green40 `#006c35`, green70 `#44c265`
- neutral90 `#e3e3e3`, neutral95 `#f2f2f2`, grey98 `#f9f9f9`

ucs semantic extras:
- `--ucs-color-global-container: #f8fafd`, `--color-ge-content-surface: #fff`,
  `--ucs-color-ge-bright-border: #e9eef6`,
  `--ucs-color-ge-bright-header-hover: #0e57d014`
- `--color-menu-item-hover-background: #dde3ea`,
  `--color-homepage-chip-outline-hover: #1e5cd9`
- success-background `#c4eed0`, success-edge `#1aa649`
- scheduling-accent `#3d43b4`, accent-fixed `#3186ff`
- empty-state title `#444746` / description `#747775`

## Ideas / report surface (session view)

Layout: left idea list (452px incl. 20px side padding), center document
(740px), right Sections rail (244px), header row with back arrow + agent icon
+ session title + Preview chip, "Session details" md-text-button at right.

| Element | Values |
|---|---|
| Session title (header) | `.tile-header-title` Google Sans Text 16px/24 w500 #1f1f1f |
| Preview chip | 12px/16 w500 ls 0.1px, color #004a77, bg #c2e7ff (secondary-container), radius 4px, padding 2px 6px |
| "Session details" button | `md-text-button` 14px/20 w500, radius 100px, padding 10px 12px, gap 8px; ACTIVE state: bg #c2e7ff, text #004a77 |
| Idea card (li.idea) | radius 10px, padding 16px, border 0.556px solid; UNSELECTED: transparent bg, border #c4c7c5 (outline-variant), margin-top 8px; SELECTED: bg #f4faff (blue-variant98), border #0b57d0 (primary) |
| Idea card hover (unselected) | bg var(--md-sys-color-surface-container) #f0f4f9; reveals export button |
| Idea rank + Elo chips | `.chip` 14px/20 w400 #1f1f1f, bg #e0f4ff (blue-variant95), radius 20px, padding 4px 12px; container flex gap 8px |
| Idea card title | 16px/24 w500, margin-bottom 4px |
| Idea card snippet | 12px/16 w400 ls 0.1px |
| Idea loading skeleton | shimmer 2s infinite, white linear-gradient overlay |
| Breadcrumb bar (doc top) | `.chip` 11px/16 w500 ls 0.1px, bg #f0f4f9, radius 5px, padding 4px 8px, full doc width |
| Doc H2 | `.header-large` Google Sans 32px/40 w400, margin-bottom 24px |
| Doc H3 | `.header-medium` Google Sans 28px/36 w400 |
| Doc numbered-item heading | Google Sans 24px/32 w400 (`.header-with-link`, 64px row) |
| Doc body | Google Sans Text 16px/24 w400 #1f1f1f |
| Doc bold labels ("Goal:", "Winning ideas") | 16px w700 |
| In-document links | default UA blue (#00e underline) + external icon — not restyled |
| "View idea" button | `md-text-button` Google Sans 14px/20 w500, color #004a77, bg #c2e7ff, radius 100px, padding 4px 12px, height 28 |
| Sections rail panel | `.navigation-block` bg #f0f4f9, radius 10px, padding 20px, width 244 |
| Sections rail header | 12px/16 w400 ls 0.1px #1f1f1f, margin-bottom 16px |
| Sections rail links | `.navigation-block li` Google Sans Text 16px w500 color #0b57d0, li height 24, 48px vertical rhythm (24px gaps), scroll-spy bolds active |
| Date chip (doc) | same 11px `.chip` recipe as home |

## Chat / setup flow

| Element | Values |
|---|---|
| User bubble | `.question-wrapper` bg #e9eef6 (surface-container-high), radius **24px 4px 24px 24px**, padding 12px 16px, max-width 484px; text 16px/24 |
| Agent row | avatar 28px + name Google Sans Text 14px w500 |
| "Thinking..." | `.thinking-message` 14px #444746 |
| Setup card | `.plan-details` bg #f0f4f9, radius 10px, padding 20px, width 760 |
| Setup card title | 22px/28 w600 Google Sans Text |
| Setup card section headings | 20px w600 Google Sans Text |
| Cancel | `md-outlined-button` radius 100px, h40, 14px w500, padding 10px 24px |
| Start session | `md-filled-button` (primary fill #0b57d0), radius 100px, h40, 14px w500, padding 10px 24px |
| Sent quick-reply ("Start session") | gray pill bubble, right-aligned |
| Error state | plain text "Something went wrong. Please try again later." + filled pill "Regenerate the response" |
| Composer (session) | placeholder "Type to edit session details", disclaimer 12px #444746 below |

## Motion

- Landing content + tournaments section: `fadeIn 0.3s ease-in-out forwards`
  (only under prefers-reduced-motion: no-preference).
- Step circle: `background-color .3s ease-in-out`.
- Agent title/labels: `opacity .125s ease`.
- Nav panel expand: `width .25s, border-radius .25s, box-shadow .25s`;
  nav labels `opacity 125ms`; search button `opacity .15s`.
- Switcher items: `background-color .2s, color .2s, box-shadow .2s`.
- Skeleton shimmer: 2s infinite linear-gradient sweep.
- Focus ring: 2px, offset -2px, duration 0ms (no animation).
- Focus-visible (links/buttons): `outline: 2px auto secondary; offset -1px`.

## Hover states

- Suggestion (sample) card: bg → surface-container-high #e9eef6.
- Recents (tournament) card: bg → surface-container-low #f8fafd.
- Idea list item (unselected): bg → surface-container #f0f4f9.
- Nav items: `color-mix(primary-container 80%, transparent)` (classic) or
  `color-mix(on-surface-variant 8%, transparent)` (next-gen).
- Menu items: label + icon → on-surface.

## Breakpoints (their @media rules)

- Base greeting is display-large; at `max-height: 900px` it drops to
  45px/52px (the measured value at 869px viewport height). Height-based!
- `max-width: 480px`: step indicator (overview-blocks) hidden.
- `max-height: 840/870px`: step indicator hidden.
- `max-height: 1000px`: agent chip hidden (unless redesign variant).
- `max-width: 1360px`: landing scrolls; main panel max-width 80%; recents
  become a grid `repeat(auto-fill, 300px)` gap 40px below the main panel.
- `max-width: 1250px` (chat view): tournament overview side panel hidden.

## Open items

- Purple decorative gradient blob on home hero: not a DOM background/canvas
  (likely inside a nested element the probe missed); approximate from
  screenshots.
- Live generation progress UI not captured (their backend errored on session
  start twice); fidelity target for live-run progress remains the core
  google-co-scientist footage.
