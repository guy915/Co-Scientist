---
version: alpha
name: Gemini Enterprise Idea Generation
description: A focused multi-agent idea generation workspace. Built on Material Design 3 semantics with Google Sans typography and the Gemini Enterprise product shell.
colors:
  # Seed — the single source of truth for the MD3 palette.
  # The full palette (primary, secondary, tertiary, surface, …) is computed
  # at runtime by applyMd3Theme() in src/lib/theme.ts.
  seed: "#1A6B6B"

  # Core MD3 roles (approximate light-mode values from the Co-Scientist green seed).
  # Dark-mode inversions are handled automatically by applyMd3Theme(true).
  primary: "#1A6B6B"
  on-primary: "#ffffff"
  primary-container: "#BFECE3"
  on-primary-container: "#00201F"
  secondary: "#625B71"
  on-secondary: "#ffffff"
  secondary-container: "#CCE8E4"
  on-secondary-container: "#051F1D"
  tertiary: "#1967D2"
  on-tertiary: "#ffffff"
  tertiary-container: "#C2E7FF"
  on-tertiary-container: "#001D35"
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
  phase-1: "hsl(174 54% 36%)"   # Generate
  phase-2: "hsl(32 95% 50%)"    # Reflect / review
  phase-3: "hsl(0 72% 51%)"     # Tournament / rank
  phase-4: "hsl(188 64% 35%)"   # Evolve / meta-review

  # Gemini product palette (--cosci-*, reference_surface.css) — exact Google
  # product colors for the shell/home surfaces. Neutral, NOT seed-tinted.
  # Light values shown; every token carries its own dark value in the
  # :root[data-theme="dark"] block. Exposed to Tailwind as cosci-* utilities.
  cosci-text: "#202124"
  cosci-muted: "#5f6368"
  cosci-subtle: "#9aa0a6"
  cosci-border: "#dadce0"
  cosci-panel: "#f1f3f4"
  cosci-bg: "#ffffff"
  cosci-rail: "#eef4ff"
  cosci-teal: "#1A6B6B"       # light-mode accent (logo, step dots, composer submit)
  cosci-green: "#7FD7BF"      # dark-mode accent (same roles)
  cosci-blue: "#1967d2"
  cosci-btn-primary-bg: "#0b57d0"   # Google-blue filled button (setup surface)

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

  # Workbench page titles ("Idea sessions", "New idea session")
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
  # Filled primary action button (MD3 filled button)
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

  # Outlined secondary button (MD3 outlined button)
  button-outlined:
    backgroundColor: transparent
    textColor: "{colors.on-surface}"
    rounded: "{rounded.full}"
    height: 40px
    padding: 0 24px

  button-outlined-active:
    textColor: "{colors.primary}"

  # Text-only button (MD3 text button)
  button-text:
    backgroundColor: transparent
    textColor: "{colors.primary}"
    rounded: "{rounded.full}"
    height: 40px
    padding: 0 12px

  # Filter chip (MD3 filter chip)
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

  # Outlined text field / textarea (MD3 outlined text field)
  input-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
    height: 56px
    padding: 16px

  # Global sticky header (layout.tsx)
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

  # Home recents card — the one card family that carries a real shadow
  recent-card:
    backgroundColor: "var(--cosci-recent-card-bg)"
    textColor: "var(--cosci-recent-card-text)"
    rounded: 0.8rem
    padding: "1.05rem 1.2rem"
    shadow: "0 1px 3px rgb(60 64 67 / 12%), 0 6px 14px -2px rgb(60 64 67 / 8%)"

  # Setup-surface filled button (Google blue, --cosci-btn-primary-*)
  setup-button-primary:
    backgroundColor: "var(--cosci-btn-primary-bg)"
    textColor: "var(--cosci-btn-primary-fg)"
    rounded: "{rounded.full}"
    height: 41.6px
    padding: 0 23.2px

  # Setup-surface radio option card (ring+dot marker, no selected tint)
  option-card:
    backgroundColor: "var(--cosci-option-bg)"
    textColor: "var(--cosci-fg)"
    rounded: 0.65rem
    padding: "0.85rem 0.95rem"

  # Canonical tooltip (data-tooltip + ucs-tooltip-*) — inverted surface
  tooltip:
    backgroundColor: "#303134"
    textColor: "#f1f3f4"
    rounded: 0.45rem
    padding: "0.34rem 0.52rem"
---

# Gemini Enterprise Idea Generation

## Overview

Idea Generation is a Gemini Enterprise-style workbench for multi-agent idea development. The UI serves users who launch and monitor idea sessions plus visitors who land on support/demo pages.

The visual language is **precise, neutral, and data-forward** — more Google product workspace than consumer app. Whitespace is generous but purposeful. Color is used sparingly and always semantically: Co-Scientist green/blue for primary actions, tonal containers for states, status colors for run outcomes. The palette adapts fluidly between light and dark modes through Material Design 3 dynamic color, not manual dark-mode overrides.

The design personality is calm competence. Typography is tight and confident. Rounded corners are present but not playful. Animation is brief and functional — a global motion baseline eases every interactive color/shadow change over 140ms so nothing snaps, plus fade-ins on load, a live dot pulse on active runs, and shimmer on skeleton loaders (see Motion baseline).

## Colors

The UI runs **two deliberately separate palettes**, and knowing which is which is essential before changing any color:

1. **MD3 dynamic palette** (`--md-sys-color-*`, bridged to `--color-th-*`) — derived at runtime from the `#1A6B6B` seed via `themeFromSourceColor`. Used for **data and semantic UI**: run status, Elo/tournament visuals, error/success states, primary actions. Its neutrals are intentionally *tinted toward the seed* by the MD3 tonal algorithm.
2. **Gemini product palette** (`--cosci-*`, in `reference_surface.css`) — the **exact Google/Gemini product colors** (`#5f6368` gray text, `#dadce0` borders, `#f1f3f4` surfaces, `#202124` ink). Used for the **shell, home, and chat/setup surfaces** (rail, composer, recents, step timeline, setup document, buttons). These are hand-picked to match Gemini 1:1 and are **neutral, not seed-tinted** — do not "consolidate" them onto the MD3 tokens, which would swap Google's true grays for teal-tinted approximations and make the UI *less* Google-accurate. Each `--cosci-*` token has its own light/dark value (many share a light value but diverge in dark), so they cannot be collapsed by light-mode hex.

### Semantic component tokens

The `--cosci-*` palette extends beyond raw colors into a **semantic component token layer**, which lives in its own file, `styles/component_tokens.css`. Every themed component surface — logs/diagnostics, danger alerts, attachment cards, toasts, radio option cards, buttons, chat bubbles, the setup document — is defined **once per mode** as a token pair (light values in `:root`, dark values in `:root[data-theme="dark"]`). Components reference the token and carry **no `dark:` variants**; a surface's light/dark appearance lives in one place. Never write an inline `dark:[#hex]` override in a component — add or extend a token pair instead.

Where possible, semantic tokens **alias baseline tokens** rather than introducing bespoke hex: the Logs system (`--cosci-logs-*`) derives every value from the step-dot accent and the neutral scale (via `var()` and `color-mix()`), so it re-themes for free with no dark block of its own. Prefer aliasing when a new surface is "the same color as X"; reserve new hex pairs for genuinely new surfaces.

The three raw-color/palette files split by role: `reference_surface.css` holds the Gemini product palette and the ideas-surface (`--cosci-idea-*`) tokens; `component_tokens.css` holds the semantic component tokens above; `shell_surface.css` / `home_surface.css` hold the shell and home *layout* rules that consume them. The import order in `styles/index.css` is `reference_surface → component_tokens → shell → home → tooltips`, so component tokens can alias palette tokens defined before them.

The mode-dependent **accent** is worth internalizing: light mode accents in the Co-Scientist teal (`--cosci-teal`, `#1A6B6B`); dark mode swaps the same roles (logo, step dots, composer submit, Logs pill) to mint green (`--cosci-green`, `#7FD7BF`). Components get this for free by using the role tokens (`--cosci-step-dot-bg`, `--cosci-composer-submit`, `--cosci-logo-color`), never the raw teal/green.

### Tailwind utilities

Both palettes are registered as named Tailwind utilities in `index.css`'s `@theme` block: the MD3 bridge as `th-*` (`bg-th-card`, `text-th-muted-fg`) and the Gemini palette as `cosci-*` (`text-cosci-fg`, `bg-cosci-panel`, `border-cosci-border`) via `--color-cosci-*` entries that mirror the underlying tokens. **Every `--cosci-*` token referenced from a component is registered** — the semantic component tokens (`--cosci-btn-*`, `--cosci-option-*`, `--cosci-logs-*`, `--cosci-danger-*`, `--cosci-attach-*`, …) and the ideas-surface tokens (`--cosci-idea-*`) all have `--color-cosci-*` mirrors. **Use the named utility; do not write arbitrary `[var(--cosci-*)]` classes.** The one legitimate arbitrary use is when the token is embedded inside a larger CSS value that isn't a plain color slot — e.g. the option marker's `bg-[radial-gradient(circle,var(--cosci-option-marker-on)…)]`.

The MD3-palette semantics below apply to the data/semantic surfaces:

- **Primary:** Co-Scientist green used for the single most important action per screen, active states, links, and the app logo mark. Never used decoratively.
- **Secondary container:** The de-facto "hover" and "selected" surface. Table rows hover to secondary-container. Active filter chips use secondary-container. Secondary navigation context uses it. Applied with restraint so it stays meaningful.
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
- **Headline-md (24px / 600):** Workbench page titles — "Idea sessions", "New idea session". Always `font-semibold tracking-tight`.
- **Body-md (16px / 400):** Default readable copy. Page description lines below page titles.
- **Body-sm (14px / 400):** Table rows, card metadata, helper text on form fields.
- **Label-lg (14px / 600):** Button labels and primary navigation links.
- **Label-md (12px / 600):** Status pill text, badge text, chip labels.
- **Label-caps (12px / 600, +0.07em tracking, uppercase):** Section labels ("HOW IT WORKS"), stat card row headers ("PROFILE", "IDEAS"), table column headers. Implemented with the `.section-label` and `uppercase tracking-wide` utility classes.

**Icons:** Material Symbols Outlined exclusively, delivered through the first-party `<Icon name="…">` component (`src/components/icon.tsx`). The glyph outlines are the authentic Material Symbols weight-400 paths, inlined as SVG (generated by `scripts/generate_icons.mjs` from `@material-symbols/svg-400`) so the set stays tree-shakeable, prerender-safe, and free of font FOUT. Icons inherit `currentColor` and size to `1em`, so set the icon's color and `font-size` on the element. Never use filled or rounded icon variants, and never hand-author glyph paths — add the icon to the generator and re-run it.

## Layout & Spacing

The **MD3 data surfaces** follow an **8px base grid**. All spacing values on those surfaces are multiples of 8px; the one exception is `xs: 4px` for micro-adjustments inside dense components.

- **Max container width:** `max-w-7xl` (1280px), horizontally centered with `mx-auto`.
- **Page padding:** `px-4` on mobile (16px), `px-6` on `sm:` and up (24px).
- **Vertical rhythm:** Page sections use `py-4 sm:py-6` (32–48px). Spacing between stacked sections is `space-y-6` (24px gap).
- **Card layout:** Dashboard runs table and grid of stat cards. Stats use a 2-col mobile / 4-col desktop grid with `gap-2`. The runs list is a table on `sm:` and above, a stack of `rounded-xl` cards below.
- **Landing layout:** Public pages use `.landing-page` max-width (76rem), fluid hero grid (text left / preview right), and `clamp()`-based padding that scales with viewport. Sections stack vertically on mobile (<900px).
- **Workbench max-width:** Run detail uses a full-width tabbed layout inside the container. The New Run form is constrained to `max-w-3xl` (768px) for comfortable single-column reading.

**Reference-matched surfaces do not use the 8px grid.** The Gemini shell, home, and chat/setup surfaces (`chat_setup_classes.ts`, `chat_home_classes.ts`, and the `reference-*` CSS) reproduce the Gemini product's own measurements, which are **literal rem/px values copied from the reference** — `[0.92rem]`, `[1.18rem]`, `[1.28rem]`, `[2.6rem]` button heights, `[5.3rem]` cards, and so on. These are deliberate, not drift: snapping them to the 8px grid would break the pixel-match with Gemini. This is the same reference-vs-system split as border-radius (see Shapes) and the recents-card shadow (see Elevation). Rule of thumb: **an MD3 data surface uses grid multiples; a `reference-*` / setup / home surface uses the reference's literal value.** When adding to a reference surface, copy the reference's measurement rather than rounding it to the grid; when building a new MD3 data surface, stay on the grid.

## Elevation & Depth

Depth is achieved primarily through **tonal layers** — page content (cards, tables, inputs) never uses drop shadows.

- **Background (Level 0):** `surface` — the lightest tint, used as the page body.
- **Cards / containers (Level 1):** `surface-container-low` with a 1px `outline-variant` border. Stat cards, run table, form containers.
- **Hover / selected (Level 2):** `secondary-container` applied via `transition-colors hover:bg-[secondary-container]`. No border change on hover.
- **Header (Level 3):** `color-mix(in srgb, surface-container 70%, transparent)` + `backdrop-blur-xl`. Creates a frosted-glass separation from page content on scroll without a heavy shadow.
- **Floating overlays:** menus, popovers, and toasts *do* carry MD3 elevation, applied with the `--md-elevation-1/2/3` shadow tokens (defined in `index.css`, with lifted opacities in dark mode). Menus/popovers use level 2; toasts use level 3. This is the one place shadow is correct — a menu detached from its trigger needs to read as floating.
- **Recents cards (the one in-page exception):** `.reference-recent-card` on the home surface carries a **soft two-layer Google-style shadow** (`0 1px 3px` + `0 6px 14px`, low opacity) that deepens slightly on hover/focus, with heavier opacities in dark mode. This matches the Gemini reference, where recents read as raised, clickable objects. Do not extend this treatment to other cards — it is a deliberate reference-matching exception, not a precedent.

Never add `box-shadow` to any other card, table, or input. The outline-variant border and tonal layers provide all the separation those need. Reserve the `--md-elevation-*` tokens strictly for surfaces that float above the page.

## Shapes

The shape language is **restrained and consistent**, but it splits along the same line as the color system: MD3 data surfaces follow a strict three-radius scale, while the Gemini shell/home/chat surfaces reproduce the reference product's geometry exactly.

**MD3 data surfaces** — three radii cover all cases:

- **`rounded-md` (8px):** Stat cards, error/alert boxes, table containers, input fields. The default for any "block" that contains data.
- **`rounded-xl` (12px):** Run cards (mobile), form containers, landing CTA box, workbench preview widget. Used when a container has more visual weight or interactive importance.
- **`rounded-full` (9999px):** All buttons (MD3 buttons are pill-shaped), status pills, filter chips, the live-dot indicator. Used for anything that is interactive or badge-like.

Never mix `rounded-xl` and `rounded-full` on the same element. Do not use `rounded-2xl` or larger on data surfaces.

**Gemini shell/home/chat surfaces** — radii match the reference, not the scale:

- **`rounded-2xl` (16px):** User chat bubbles, the setup document, the started-session card, composer image previews.
- **`0.8rem` (12.8px):** Recents cards.
- **`0.65rem` (10.4px):** Radio option cards.
- **`rounded-full`:** All pills and icon buttons, same as everywhere else.

These values are copied from the Gemini product and should not be "normalized" onto the three-radius scale — matching the reference wins. New shell components take their radius from the closest reference component, not from the MD3 scale.

## Components

> **Architecture note.** Components are first-party React elements styled to the Material Design 3 spec — not the `@material/web` custom-element library. MD3 is followed as a *design language* (dynamic color via `material-color-utilities`, the type/shape/elevation scales, and state layers), which is how Google's own flagship products are built. Keep components as semantic HTML (`<button>`, `<nav>`, `role="menu"`) styled with the shared tokens below; do not reintroduce `md-*` custom elements.

### Class-name prefixes

Bespoke CSS class names (as opposed to Tailwind utilities) use **exactly two prefixes**, split by origin. New CSS classes must take one of them; do not invent a third family or revive the retired ones (`google-*`, `gemini-*`, `cosci-*` as a *class* prefix, `idea-*`, `wb-*` beyond the two below).

- **`ucs-*`** — app **shell chrome** the reference doesn't dictate: the app shell grid, nav rail items, side content, chat list, workspace wrappers, and the canonical tooltip system (`ucs-tooltip-*`).
- **`reference-*`** — surfaces that reproduce a **specific Gemini reference** screen 1:1: the composer, recents cards, step timeline, chat bubbles, setup document, spec grid, option cards, report tabs/toast, workspace-main.

Two historical strays remain by intent: `wb-skeleton` and `wb-link` (generic workbench utilities), and `md-state` / `md-elevation-*` (MD3 primitives). Everything else is a Tailwind utility. Note the `--cosci-*` **custom-property** prefix is unrelated to class names — it's the token namespace (see Colors) and stays.

### Interaction states

Every interactive element gets an MD3 **state layer** — a translucent `currentColor` overlay that fades in on hover (8%), focus (10%), and press (10%) over ~120ms. Use the reusable `.md-state` utility (`index.css`), which paints the layer beneath the element's content via a `::before`-safe `::after` at `z-index:-1`. Elements that already use `::after` (e.g. the run-detail tabs, which use it for the selected underline) get an equivalent `::before` state layer. Respect `prefers-reduced-motion`.

### Motion baseline

**Nothing snaps.** A global baseline in `index.css` transitions `background-color`, `border-color`, `color`, `box-shadow`, and `opacity` over **140ms** with the MD3 standard easing (`cubic-bezier(0.2, 0, 0, 1)`) on every `button`, `a`, `summary`, `[role="button"]`, `[role="tab"]`, `input`, `select`, and `textarea`. Component-specific transitions (higher specificity) still win where set — e.g. recents cards ease shadow/border over 160ms, the sidebar rail animates `grid-template-columns` over 240ms with nav labels fading/collapsing in sync.

Two guardrails:

- **Theme switching is exempt.** `theme_context.tsx` adds a `.theme-switching` class for one frame on light/dark toggle, which force-disables all transitions so the entire page doesn't animate through the palette swap.
- **`prefers-reduced-motion: reduce` disables every transition** — the baseline, the sidebar, the state layers, and any component-specific motion. Any new animation must include this media-query escape.

Keep discrete animations under 200ms (`wb-fade-in` is 180ms); the 240ms sidebar is the ceiling for structural motion.

### Buttons

Buttons are pill-shaped (`rounded-full`) semantic `<button>` elements following MD3 button roles. One filled primary action per screen; secondary actions are outlined or text.

- **Filled** — primary CTA only (one per screen: "Start research", "Send"). Primary background, `on-primary` label, state layer on hover/press.
- **Outlined** — secondary/context actions. `outline-variant` border, no fill.
- **Text** — tertiary inline actions and toggles (e.g. "Advanced settings"), often with a trailing `expand_more` / `expand_less` icon.
- **Icon** — icon-only actions (theme toggle, log console, composer source buttons). Circular, transparent, state layer on hover/press. Icon-button hovers are always **neutral gray** (`--cosci-hover` / `bg-cosci-hover`), never tinted.

**Setup/chat-surface buttons** (`--cosci-btn-*` tokens) — the Gemini setup flow uses Google's own button colors, not the MD3 teal:

- **Primary (filled)** — Google blue `#0b57d0` with white label in light mode; in dark mode a muted blue container (`#1d3354`) with light-blue label. Used for "Start" on the setup document.
- **Outline** — blue border and blue label in both modes (`#1a73e8`/`#1967d2` light, `#8ab4f8` dark), transparent fill, tinted hover wash. Used for follow-up actions ("View session details").
- **Secondary** — neutral gray border and ink label, gray hover. Used for "Cancel"-grade actions.
- All three share a **disabled trio** (`--cosci-btn-disabled-border/bg/fg`) and are pill-shaped like every other button.

The composer submit button is neither of these systems — it uses the mode-dependent accent (`--cosci-composer-submit`: teal in light, mint green in dark).

### Filter Chips

Pill-shaped (`rounded-full`) `<button>` chips. Selected chips apply `secondary-container` background; unselected use `surface-container`. Never use more than 5–6 chips in a row; wrap gracefully on mobile.

### Inputs

Text inputs and textareas are semantic `<input>` / `<textarea>` styled as MD3 outlined fields — `outline-variant` border, `rounded-md`, no shadow. Always set `width: 100%` and let the parent grid/flex control the actual width. The research goal composer is a growing textarea with inline source/send controls.

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

The shell header follows the Gemini Enterprise reference: left rail, `Gemini Enterprise` product lockup, optional `Plus` chip, compact action icons, and a context-sensitive centered page title.

### Tables

Run list table on Dashboard uses `sm:block hidden`. Structure: `thead` with `secondary-container` background, `tbody` rows with `hover:bg-[secondary-container]` and `border-t outline-variant`. On mobile, replaced entirely by RunCard stack. Column headers use `label-lg font-semibold`.

### Progress & Loading

- **Skeleton loaders:** `.wb-skeleton` — neutral gray shimmer animation, colored by the `--cosci-skeleton-bg` token pair (light `#eceff1` / dark `#3a3f42`) so it themes like everything else rather than via a hardcoded hex. Used while API calls resolve.
- **Linear / circular progress** — first-party progress indicators using the `primary` token, shown in the run detail header (iteration progress) and while tab streams load.

### Tabs (Run Detail)

A first-party `<nav>` of `<button>` tabs (`.reference-report-tabs`) for the run views: Goal Details, Learning, Research Overview, All Ideas. The active tab is `primary`-colored with a bottom underline drawn via `::after`; hover/focus paints an MD3 state layer via `::before` (see Interaction states). Tab content panels are full-width below the tab bar.

### Chat & setup surface

The session chat column (`chat_setup_classes.ts`) is a Gemini-style conversation:

- **User bubbles** — `rounded-2xl`, `--cosci-user-bubble-bg` (soft blue-gray light / neutral dark), max-width ~31rem, right-aligned. **Model turns are bubble-less** — plain text on the workspace background at full column width.
- **Message actions** (Copy/Edit prompt) — icon buttons revealed on hover/focus of the turn, neutral-gray hover, no outline ring.
- **Setup document** — a `rounded-2xl` `--cosci-setup-doc-bg` sheet containing the plan spec grid, option-card radio groups, and the blue setup buttons.
- **Started-session card** — a `rounded-2xl` teal **gradient** card (the one gradient surface in the app, defined in `reference_surface.css` with a brighter dark-mode variant), white text, with an outlined-white "Open" pill.
- **Attachment cards** — `--cosci-attach-*` tokens; image previews stay square with the filename in a tooltip.

### Logs / Diagnostics

A header **Logs pill** (filled with the mode accent — teal in light, mint in dark — plus an entry-count badge) opens a floating **popover panel** (`ucs-popover--logs`, MD3 elevation) listing live SSE diagnostics from the backend. Every color in the panel is a `--cosci-logs-*` token that **aliases a baseline token** — the accent from the step-dot pair, surfaces/borders/text from the neutral scale — so the panel re-themes with no dark overrides of its own. Status chips are filled (accent for ok, danger pair for errors); Clear/Copy actions are outlined in the accent; event payloads render in monospace on a `--cosci-logs-panel-bg` code block.

### Tooltips

One canonical tooltip system: set `data-tooltip="…"` plus the `.ucs-tooltip-anchor` class — build the class list with `tooltipClassNames()` in `tooltip.ts` rather than hand-assembling modifiers. The tooltip is an **inverted surface** — dark chip (`#303134`) in light mode, light chip (`#f1f3f4`) in dark mode — with a small shadow, 0.78rem medium text, and a subtle scale/translate entrance on hover/focus-visible. Placement modifiers: `.ucs-tooltip-top/bottom/left/right`, alignment `.ucs-tooltip-align-start/end`, and `.ucs-tooltip-wrap` for multi-line content. Never hand-roll a bespoke tooltip; new affordances must use this system.

**Cascade, not `!important`.** `tooltips.css` is **unlayered author CSS imported last** (after Tailwind's `@layer utilities`), so its rules already outrank utility classes — an `overflow-hidden` utility on an anchor can't clip the tooltip, and no declaration needs `!important`. This is deliberate and load-bearing: keep the file unlayered and imported last rather than reaching for `!important` to win a specificity fight. The placement/alignment modifiers share the base selector's specificity and rely on source order (they appear after the base rule).

### Scrollbars

Scrollbars are themed globally (`index.css`) as a **trackless floating thumb**, Google style: no channel behind the thumb, just a rounded gray pill (`#bdc1c6` light / `#5f6368` dark, darkening on hover) inset by a 3px transparent border inside a 14px hit area. Implementation note: the styling deliberately uses the `::-webkit-scrollbar` pseudos and does **not** set the standard `scrollbar-width` / `scrollbar-color` properties — in Chromium those suppress the webkit pseudos.

### Radio option cards

The setup flow's Focus/Tier pickers are card-shaped radio groups (`--cosci-option-*` tokens): a transparent-bordered card that gains a border and tinted background on hover/focus-within only. **Selection is communicated solely by the radio marker** — a Material-style ring with a centered inner dot (radial-gradient), gray when idle, blue when selected. Selected cards do *not* tint their background.

### Empty states

Run-tab empty placeholders use the shared `EmptyState` component (`components/empty_state.tsx`): a centered `rounded` bordered box, `outline-variant` border, `on-surface-variant` text. Don't inline one-off empty-state markup in tabs.

## Do's and Don'ts

- **Do** use `primary` for one action per screen only. If there are two actions, one is `md-outlined-button`.
- **Do** apply `outline-variant` for all borders. Never use raw hex colors for borders.
- **Do** use `on-surface-variant` for all secondary/helper text. Never use `opacity: 0.5` on foreground text.
- **Do** let `applyMd3Theme()` generate color tokens. Never hardcode MD3 palette values like `--md-sys-color-primary`.
- **Do** use Material Symbols Outlined via the `<Icon>` component. Size it with `font-size` (icons render at `1em`) and color it with `color` (icons use `currentColor`).
- **Do** use `wb-fade-in` (180ms ease-out) on content that appears after data loads. Keep animations under 200ms.
- **Do** theme new component surfaces with paired light/dark `--cosci-*` tokens in `component_tokens.css`. Never write inline `dark:[#hex]` overrides in components.
- **Do** alias existing baseline tokens (via `var()` / `color-mix()`) when a new surface should match an existing color, as the Logs tokens do.
- **Do** register every component-referenced `--cosci-*` token as a `--color-cosci-*` utility and use the named class (`bg-cosci-btn-primary-bg`). Reserve arbitrary `[var(--cosci-*)]` for tokens embedded in a non-color value (e.g. a gradient).
- **Do** give new bespoke CSS classes a `ucs-*` (shell chrome) or `reference-*` (Gemini-reference surface) prefix. Don't invent a third family or revive `google-*` / `gemini-*` / `idea-*`.
- **Do** use the `data-tooltip` + `ucs-tooltip-*` system for any new tooltip, and keep `tooltips.css` unlayered + imported last so it wins without `!important`.
- **Don't** add `box-shadow` to cards or inputs (sole exception: the home recents cards, which match the Gemini reference). Tonal elevation is sufficient everywhere else.
- **Don't** use `rounded-2xl` or larger on MD3 data surfaces. The three-size system (md / xl / full) covers those; Gemini shell/chat surfaces copy the reference geometry instead (see Shapes).
- **Don't** snap the arbitrary rem values on reference-matched surfaces (setup / home / `reference-*`) onto the 8px grid — they are literal reference measurements. Conversely, don't introduce off-grid values on MD3 data surfaces (see Layout & Spacing).
- **Don't** fold the `--cosci-*` product palette into the MD3 tokens, and don't use raw `--cosci-teal` / `--cosci-green` directly — use the accent role tokens so light/dark swap correctly.
- **Don't** give any element a `prefers-reduced-motion`-exempt animation; every transition must have the reduce escape.
- **Don't** use more than two font weights on a single card or panel.
- **Don't** put primary-colored text and a primary-colored button in the same visual cluster — one of them must defer.
- **Don't** use the phase colors (phase-0 through phase-4) for anything other than agent pipeline stage indicators.
- **Don't** introduce new semantic colors without adding both light and dark hardcoded overrides to `index.css`.
