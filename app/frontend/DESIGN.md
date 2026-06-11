---
version: alpha
name: Co-Scientist Workbench
description: A focused scientific research workbench for AI-assisted hypothesis generation. Built on Material Design 3 semantics with Google Sans typography. The palette is generated at runtime from a single seed color using @material/material-color-utilities.
colors:
  # Seed — the single source of truth for the MD3 palette.
  # The full palette (primary, secondary, tertiary, surface, …) is computed
  # at runtime by applyMd3Theme() in src/lib/theme.ts.
  seed: "#1A6B6B"

  # Core MD3 roles (approximate light-mode values from the teal seed).
  # Dark-mode inversions are handled automatically by applyMd3Theme(true).
  primary: "#00696C"
  on-primary: "#ffffff"
  primary-container: "#9CF1F3"
  on-primary-container: "#002021"
  secondary: "#4A6364"
  on-secondary: "#ffffff"
  secondary-container: "#CCE8E9"
  on-secondary-container: "#051F20"
  tertiary: "#4B607C"
  on-tertiary: "#ffffff"
  tertiary-container: "#D3E4FF"
  on-tertiary-container: "#041C35"
  surface: "#F5FAFA"
  surface-container-low: "#EFF4F4"
  surface-container: "#E9EEEE"
  on-surface: "#171D1D"
  on-surface-variant: "#3F4949"
  outline: "#6F7979"
  outline-variant: "#BEC9C9"
  error: "#BA1A1A"
  on-error: "#ffffff"
  error-container: "#FFDAD6"
  on-error-container: "#410002"

  # Semantic extras — no MD3 equivalent; hardcoded in index.css.
  success: "hsl(142 71% 45%)"
  success-container: "hsl(138 38% 93%)"
  on-success-container: "hsl(138 45% 20%)"
  warning: "hsl(38 92% 50%)"
  warning-container: "hsl(38 92% 92%)"
  on-warning-container: "hsl(38 92% 16%)"
  info: "hsl(199 89% 48%)"
  link: "hsl(221 83% 53%)"

  # Agent-pipeline phase colors (one per stage, shown as progress steps).
  phase-0: "hsl(142 71% 45%)"   # Supervisor / plan
  phase-1: "hsl(271 69% 55%)"   # Generate
  phase-2: "hsl(32 95% 50%)"    # Reflect / review
  phase-3: "hsl(0 72% 51%)"     # Tournament / rank
  phase-4: "hsl(248 53% 58%)"   # Evolve / meta-review

typography:
  # Landing / marketing headings
  display:
    fontFamily: Google Sans
    fontSize: 64px
    fontWeight: 500
    lineHeight: 0.98
    letterSpacing: -0.055em

  headline-lg:
    fontFamily: Google Sans
    fontSize: 40px
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: -0.045em

  # Workbench page titles ("Research runs", "New research run")
  headline-md:
    fontFamily: Google Sans
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: -0.02em

  headline-sm:
    fontFamily: Google Sans
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.2

  body-lg:
    fontFamily: Google Sans
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.5

  # Default readable copy
  body-md:
    fontFamily: Google Sans
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.55

  # Table rows, card metadata, helper text
  body-sm:
    fontFamily: Google Sans
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5

  # Button labels, nav links, stat card labels
  label-lg:
    fontFamily: Google Sans
    fontSize: 14px
    fontWeight: 600
    lineHeight: 1

  # Chip text, badge text, small metadata
  label-md:
    fontFamily: Google Sans
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1

  # Section labels, table-header uppercase text ("PROFILE", "IDEAS")
  label-caps:
    fontFamily: Google Sans
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1
    letterSpacing: 0.07em

rounded:
  sm: 4px
  md: 8px
  lg: 12px
  xl: 12px
  full: 9999px

spacing:
  base: 8px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
  section: 64px
  container-x: 24px
  page-max-width: 1280px

components:
  # Filled primary action button (md-filled-button)
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label-lg}"
    rounded: "{rounded.full}"
    height: 40px
    padding: 0 24px

  button-primary-hover:
    backgroundColor: "{colors.primary-container}"
    textColor: "{colors.on-primary-container}"

  # Outlined secondary button (md-outlined-button)
  button-outlined:
    backgroundColor: transparent
    textColor: "{colors.on-surface}"
    rounded: "{rounded.full}"
    height: 40px
    padding: 0 24px

  button-outlined-active:
    textColor: "{colors.primary}"

  # Text-only button (md-text-button)
  button-text:
    backgroundColor: transparent
    textColor: "{colors.primary}"
    rounded: "{rounded.full}"
    height: 40px
    padding: 0 12px

  # Filter chip (md-filter-chip inside md-chip-set)
  chip-filter:
    backgroundColor: "{colors.surface-container}"
    textColor: "{colors.on-surface-variant}"
    rounded: "{rounded.full}"
    height: 32px
    padding: 0 16px

  chip-filter-selected:
    backgroundColor: "{colors.secondary-container}"
    textColor: "{colors.on-secondary-container}"

  # Data/content card — surface-container-low background, 1px border
  card:
    backgroundColor: "{colors.surface-container-low}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.lg}"
    padding: 16px

  # Inline stat card (Dashboard stats row)
  stat-card:
    backgroundColor: "{colors.surface-container-low}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
    padding: 12px

  # Status pill badge (RunStatusPill component)
  status-pill:
    rounded: "{rounded.full}"
    padding: 2px 8px
    typography: "{typography.label-md}"

  # status-pill variants mirror RunStatus
  status-pill-running:
    backgroundColor: "{colors.tertiary-container}"
    textColor: "{colors.on-tertiary}"

  status-pill-completed:
    backgroundColor: "{colors.success-container}"
    textColor: "{colors.on-success-container}"

  status-pill-failed:
    backgroundColor: "{colors.error-container}"
    textColor: "{colors.on-error-container}"

  status-pill-draft:
    backgroundColor: "{colors.surface-container}"
    textColor: "{colors.on-surface-variant}"

  # Outlined text field / textarea (md-outlined-text-field)
  input-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
    height: 56px
    padding: 16px

  # Global sticky header (Layout.tsx)
  header:
    backgroundColor: "color-mix(in srgb, {colors.surface-container} 70%, transparent)"
    height: 52px
    padding: 12px 24px

  # Landing page public button — filled variant
  public-button-filled:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.full}"
    height: 48px
    padding: 0 22px

  # Landing page public button — outlined variant
  public-button-outlined:
    backgroundColor: transparent
    textColor: "{colors.on-surface}"
    rounded: "{rounded.full}"
    height: 48px
    padding: 0 22px
---

# Co-Scientist Workbench

## Overview

Co-Scientist is a workbench for AI-driven scientific hypothesis generation. The UI serves two distinct audiences: scientists who use the workbench to launch and monitor research runs, and visitors who land on the public landing page.

The visual language is **precise, neutral, and data-forward** — more laboratory instrument than consumer app. Whitespace is generous but purposeful. Color is used sparingly and always semantically: teal for primary actions, tonal containers for states, status colors for run outcomes. The palette adapts fluidly between light and dark modes through Material Design 3 dynamic color, not manual dark-mode overrides.

The design personality is calm competence. Typography is tight and confident. Rounded corners are present but not playful. Animation is brief and functional — fade-ins on load, a live dot pulse on active runs, shimmer on skeleton loaders.

## Colors

The palette is derived at runtime from a single teal seed (`#1A6B6B`) using the MD3 `themeFromSourceColor` algorithm. This means exact hex values shift slightly between builds but the semantic relationships — primary/on-primary, container/on-container — are always correct and WCAG-compliant.

- **Primary (#00696C):** Mid-teal used for the single most important action per screen, active states, links, and the app logo mark. Never used decoratively.
- **Secondary container (CCE8E9):** The de-facto "hover" and "selected" surface. Table rows hover to secondary-container. Active filter chips use secondary-container. Secondary navigation context uses it. Applied with restraint so it stays meaningful.
- **Surface / surface-container-low (EFF4F4):** The card background. All data cards and form containers sit one tone above the base surface. Never pure white; always tinted by the seed.
- **On-surface-variant (#3F4949):** Used for all secondary/helper text — stat card labels, metadata columns, column headers, placeholder text, and the `section-label` caps-uppercase style.
- **Outline-variant (#BEC9C9):** The default 1px border for every card, table, section divider, and input. Borders never use a raw color — always this token.
- **Error / error-container:** Reserved strictly for failed/blocked run states and form validation. Not used for warnings or info.
- **Success, Warning, Info:** Hardcoded semantic extras with no MD3 counterpart. Success maps to `completed` run status and positive metrics. Warning is unused in current components but reserved. Info is used in the `LogConsole` and streaming events.
- **Phase colors (0–4):** Five distinct hues marking stages of the agent pipeline (Supervisor → Generate → Reflect → Tournament → Evolve). Displayed as colored progress segments on the run detail header. Never reused for other purposes.

Dark mode: `applyMd3Theme(true)` regenerates all `--md-sys-color-*` tokens automatically. The few hardcoded tokens (`success`, `warning`, `info`, `link`) have explicit dark overrides in `:root[data-theme="dark"]`.

## Typography

A single typeface — **Google Sans** — covers every typographic role. No fallback stacks introduce visual variation; `system-ui, sans-serif` is a render-failure fallback only.

- **Display (64px / weight 500):** Landing page H1 only. Tight letter-spacing (−0.055em), line-height near 1. Used at fluid `clamp()` sizes.
- **Headline-lg (40px / 500):** Landing section headings and demo page H1.
- **Headline-md (24px / 600):** Workbench page titles — "Research runs", "New research run". Always `font-semibold tracking-tight`.
- **Body-md (16px / 400):** Default readable copy. Page description lines below page titles.
- **Body-sm (14px / 400):** Table rows, card metadata, helper text on form fields.
- **Label-lg (14px / 600):** Button labels and primary navigation links.
- **Label-md (12px / 600):** Status pill text, badge text, chip labels.
- **Label-caps (12px / 600, +0.07em tracking, uppercase):** Section labels ("HOW IT WORKS"), stat card row headers ("PROFILE", "IDEAS"), table column headers. Implemented with the `.section-label` and `uppercase tracking-wide` utility classes.

**Icons:** Material Symbols Outlined exclusively. Icon size defaults to 24px and is adjusted via `--md-icon-size` CSS variable when embedded in components. Never use filled or rounded icon variants.

## Layout & Spacing

The layout follows an **8px base grid**. All spacing values are multiples of 8px. The one exception is `xs: 4px` for micro-adjustments inside dense components.

- **Max container width:** `max-w-7xl` (1280px), horizontally centered with `mx-auto`.
- **Page padding:** `px-4` on mobile (16px), `px-6` on `sm:` and up (24px).
- **Vertical rhythm:** Page sections use `py-4 sm:py-6` (32–48px). Spacing between stacked sections is `space-y-6` (24px gap).
- **Card layout:** Dashboard runs table and grid of stat cards. Stats use a 2-col mobile / 4-col desktop grid with `gap-2`. The runs list is a table on `sm:` and above, a stack of `rounded-xl` cards below.
- **Landing layout:** Public pages use `.landing-page` max-width (76rem), fluid hero grid (text left / preview right), and `clamp()`-based padding that scales with viewport. Sections stack vertically on mobile (<900px).
- **Workbench max-width:** Run detail uses a full-width tabbed layout inside the container. The New Run form is constrained to `max-w-3xl` (768px) for comfortable single-column reading.

## Elevation & Depth

Depth is achieved through **tonal layers** — no drop shadows anywhere in the workbench.

- **Background (Level 0):** `surface` — the lightest tint, used as the page body.
- **Cards / containers (Level 1):** `surface-container-low` with a 1px `outline-variant` border. Stat cards, run table, form containers.
- **Hover / selected (Level 2):** `secondary-container` applied via `transition-colors hover:bg-[secondary-container]`. No border change on hover.
- **Header (Level 3):** `color-mix(in srgb, surface-container 70%, transparent)` + `backdrop-blur-xl`. Creates a frosted-glass separation from page content on scroll without a heavy shadow.
- **Modals / dialogs:** `md-dialog` web component handles elevation internally per MD3 spec.

Never add `box-shadow` to cards, tables, or inputs. The outline-variant border provides all the separation needed.

## Shapes

The shape language is **restrained and consistent**. Three radii cover all cases:

- **`rounded-md` (8px):** Stat cards, error/alert boxes, table containers, input fields. The default for any "block" that contains data.
- **`rounded-xl` (12px):** Run cards (mobile), form containers, landing CTA box, workbench preview widget. Used when a container has more visual weight or interactive importance.
- **`rounded-full` (9999px):** All buttons (MD3 buttons are pill-shaped), status pills, filter chips, the live-dot indicator. Used for anything that is interactive or badge-like.

Never mix `rounded-xl` and `rounded-full` on the same element. Do not use `rounded-2xl` or larger.

## Components

### Buttons

All buttons use Material Web custom elements. Never substitute plain `<button>` elements styled to look like MD3 buttons.

- `md-filled-button` — primary CTA only (one per screen: "New run", "Create first run", "Start"). Pill-shaped, primary background.
- `md-outlined-button` — secondary navigation or context-switch actions ("Workbench", "Dashboard"). Pill-shaped, no fill.
- `md-text-button` — tertiary inline actions (e.g. "Advanced settings" toggle, cancel flows).
- `md-icon-button` / `md-filled-icon-button` — icon-only actions. Used for the ThemeToggle and log console open/close.

Buttons that open inline toggle content (like Advanced settings) use `md-text-button` with a trailing `expand_more` / `expand_less` icon.

### Filter Chips

`md-chip-set` containing `md-filter-chip` elements. Used on the Dashboard to filter runs by status. Selected chips apply `secondary-container` background. Never use more than 5–6 chips in a row; wrap gracefully on mobile.

### Inputs

`md-outlined-text-field` handles all text input and textarea. Always set `width: 100%` and let the parent grid/flex control the actual width. The search field on Dashboard uses `type="search"`. The research goal textarea uses `type="textarea"` with `rows={4}`.

### Cards

Two card patterns:

1. **StatCard** — `rounded` border + `surface-container-low` background, 12px padding. Label in `label-caps` + `on-surface-variant`, value in `text-2xl font-semibold`, optional sub-line in `body-sm` + `on-surface-variant`.
2. **RunCard** (mobile) — `rounded-xl` border + `surface-container-low` background, 16px padding. Contains status pill, research goal as H2, and a 3-col data grid (`PROFILE / IDEAS / CREATED`).

### Status Pills

`RunStatusPill` renders a `rounded-full` inline badge using container/on-container color pairs:
- `running` / `queued` / `synthesizing` → `tertiary-container` / `on-tertiary`
- `completed` → `success-container` / `on-success-container`
- `failed` / `blocked` → `error-container` / `on-error-container`
- `draft` / `cancelled` → `surface-variant` / `on-surface-variant`

### Navigation

The header contains: logo mark (teal SVG flask), app name ("Co-Scientist"), optional public nav links, ThemeToggle icon button, and a context-sensitive `md-outlined-button`. The button reads "Workbench" on public routes and "Dashboard" on workbench routes. On workbench routes, a LogConsole trigger also appears (hidden on mobile).

### Tables

Run list table on Dashboard uses `sm:block hidden`. Structure: `thead` with `secondary-container` background, `tbody` rows with `hover:bg-[secondary-container]` and `border-t outline-variant`. On mobile, replaced entirely by RunCard stack. Column headers use `label-lg font-semibold`.

### Progress & Loading

- **Skeleton loaders:** `.wb-skeleton` — shimmer animation over `secondary` → `accent` → `secondary` gradient. Used while API calls resolve.
- **Live dot:** `.wb-live-dot` — pulsing green circle indicating an active run. Appears inline next to "Running" status.
- `md-linear-progress` — used inside run detail header to show iteration progress.
- `md-circular-progress` — used for stream-loading states within tabs.

### Tabs (Run Detail)

`md-tabs` containing `md-primary-tab` elements for the five run views: Overview, Ideas, Evidence, Tournament, Report. Tab labels are single words. The active tab uses MD3 primary underline indicator automatically. Tab content panels are full-width below the tab bar.

### Log Console

A collapsible side-drawer (desktop) or sheet (mobile) showing live SSE events from the backend. Background `surface-container-highest`, monospace font for log lines, color-coded by event type using the phase and semantic color tokens.

## Do's and Don'ts

- **Do** use `primary` for one action per screen only. If there are two actions, one is `md-outlined-button`.
- **Do** apply `outline-variant` for all borders. Never use raw hex colors for borders.
- **Do** use `on-surface-variant` for all secondary/helper text. Never use `opacity: 0.5` on foreground text.
- **Do** let `applyMd3Theme()` generate color tokens. Never hardcode MD3 palette values like `--md-sys-color-primary`.
- **Do** use Material Symbols Outlined. Size via `--md-icon-size`, not `font-size` on the element.
- **Do** use `wb-fade-in` (180ms ease-out) on content that appears after data loads. Keep animations under 200ms.
- **Don't** add `box-shadow` to cards or inputs. Tonal elevation is sufficient.
- **Don't** use `rounded-2xl` or larger. The three-size system (md / xl / full) covers all cases.
- **Don't** use more than two font weights on a single card or panel.
- **Don't** put primary-colored text and a primary-colored button in the same visual cluster — one of them must defer.
- **Don't** use the phase colors (phase-0 through phase-4) for anything other than agent pipeline stage indicators.
- **Don't** introduce new semantic colors without adding both light and dark hardcoded overrides to `index.css`.
