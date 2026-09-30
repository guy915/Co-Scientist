---
version: alpha
name: Co-Scientist
description: A focused multi-agent idea-generation workbench. Built on Material Design 3 semantics with the Google Sans family and a Gemini Enterprise-style product shell.
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

  # Semantic extras — no MD3 equivalent; hardcoded as --color-th-* in
  # theme_tokens.css, with explicit dark overrides in index.css's
  # :root[data-theme="dark"] block. success + warning are in active use (run
  # completion and safety-screening activity tones); info + link are defined
  # but currently unreferenced — reserved.
  success: "hsl(142 71% 45%)"
  success-container: "hsl(138 38% 93%)"
  on-success-container: "hsl(138 45% 20%)"
  warning: "hsl(38 92% 50%)"
  warning-container: "hsl(38 92% 92%)"
  on-warning-container: "hsl(38 92% 16%)"
  info: "hsl(199 89% 48%)"
  link: "hsl(221 83% 53%)"

  # Gemini product palette (--cosci-*, reference_surface.css) — the MD3 sys
  # neutrals + primary the live Gemini Enterprise product actually uses for the
  # shell/home surfaces (measured 2026-07 from a capture since deleted from
  # references/; read it out of git history). Faintly warm neutrals, NOT the classic blue-grey
  # Google ramp. Light values shown; every token carries its own dark value in
  # the :root[data-theme="dark"] block. Exposed to Tailwind as cosci-* utilities.
  cosci-text: "#1f1f1f"       # MD3 on-surface (dark: pure #fff, as the product overrides)
  cosci-muted: "#747775"      # MD3 outline (dark: on-surface-variant #c4c7c5)
  cosci-subtle: "#9aa0a6"
  cosci-border: "#c4c7c5"     # MD3 outline-variant
  cosci-panel: "#f0f4f9"      # MD3 surface-container
  cosci-bg: "#ffffff"
  cosci-rail: "#e9eef6"       # MD3 surface-container-high (dark: surface-container #1e1f20)
  cosci-teal: "#1A6B6B"       # light-mode accent (composer submit)
  cosci-green: "#7FD7BF"      # brand mint; the DARK-mode accent resolves to #68D0C0
  cosci-accent: "#238A84"     # the app accent: logo, step dots, popover actions, focus rings (dark swaps to the green accent; see Colors)
  cosci-blue: "#0b57d0"
  cosci-btn-primary-bg: "#0b57d0"   # Google-blue filled button (setup surface; dark: #a8c7fa)

typography:
  # Two faces, one family. Google Sans is the DISPLAY face (home greeting,
  # document headings, settings titles, product wordmark — --font-gsans /
  # `font-gsans`); Google Sans Text is the PLAIN face for all running UI text
  # and the :root default. Both are self-hosted woff2 (400/500/700); see
  # Typography in the body.

  # Home greeting ("Hello, …"). Fluid: clamp(2.25rem, 3.4vw, 2.8125rem).
  display:
    fontFamily: Google Sans
    fontSize: 45px
    fontWeight: 400
    lineHeight: 1.156

  # Goal-report document H2 (run detail) + ideas detail-pane headings
  headline-lg:
    fontFamily: Google Sans
    fontSize: 32px
    fontWeight: 400
    lineHeight: 1.25

  # Goal-report document H3
  headline-md:
    fontFamily: Google Sans
    fontSize: 28px
    fontWeight: 400
    lineHeight: 1.29

  # Settings dialog title
  title-lg:
    fontFamily: Google Sans
    fontSize: 22px
    fontWeight: 500
    lineHeight: 1.2

  # Product lockup / wordmark ("Co-Scientist")
  title-md:
    fontFamily: Google Sans
    fontSize: 20px
    fontWeight: 500
    lineHeight: 1.2

  # Settings card titles
  title-sm:
    fontFamily: Google Sans
    fontSize: 16.8px
    fontWeight: 500
    lineHeight: 1.2

  # Setup-document title (plan spec sheet)
  setup-title:
    fontFamily: Google Sans Text
    fontSize: 23.2px
    fontWeight: 600
    lineHeight: 1.25

  # Setup-document section headings ("Focus area", "Research plan")
  setup-section:
    fontFamily: Google Sans Text
    fontSize: 18.9px
    fontWeight: 700
    lineHeight: 1.3

  # Default readable copy (chat turns, report body, helper text)
  body-md:
    fontFamily: Google Sans Text
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.55

  # Card metadata, recents meta lines, helper text
  body-sm:
    fontFamily: Google Sans Text
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5

  # Button labels, nav links, tab labels
  label-lg:
    fontFamily: Google Sans Text
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1

  # Chip text (Elo/rank/unverified), badges, small metadata
  label-md:
    fontFamily: Google Sans Text
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1

rounded:
  # Tailwind v4's default radius scale, unchanged except for `--radius`
  # (theme_tokens.css), which backs the bare `rounded` utility EmptyState uses.
  # `rounded-sm` is unused.
  sm: 4px
  base: 8px
  md: 6px
  lg: 8px
  xl: 12px
  2xl: 16px
  full: 9999px

spacing:
  base: 8px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
  container-x: 24px
  content-max-width: 928px   # run-detail document column, w-[min(100% - 3rem, 58rem)]

components:
  # MD3 filled primary button (rare — e.g. the error-boundary "Reload" action)
  button-filled:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label-lg}"
    rounded: "{rounded.full}"
    height: 40px
    padding: 0 20px

  # Setup-surface filled button (Google blue, --cosci-btn-primary-*;
  # dark mode inverts to #a8c7fa fill / #062e6f label)
  setup-button-primary:
    backgroundColor: "var(--cosci-btn-primary-bg)"
    textColor: "var(--cosci-btn-primary-fg)"
    rounded: "{rounded.full}"
    height: 41.6px
    padding: 0 23.2px

  # Setup-surface outlined button (outline border, primary-colored label)
  setup-button-outline:
    backgroundColor: transparent
    textColor: "var(--cosci-btn-outline-fg)"
    rounded: "{rounded.full}"
    height: 41.6px
    padding: 0 23.2px

  # Setup-surface secondary button (neutral border + ink label)
  setup-button-secondary:
    backgroundColor: transparent
    textColor: "var(--cosci-fg)"
    rounded: "{rounded.full}"
    height: 41.6px
    padding: 0 23.2px

  # Global sticky header bar (.ucs-header-action-bar) — solid fill, no blur
  header:
    backgroundColor: "var(--cosci-surface-bg)"
    height: 64px
    padding: 0 26px

  # Home composer (.reference-composer) — light casts a soft shadow via
  # --cosci-composer-shadow; dark is shadowless and borderless
  composer:
    backgroundColor: "var(--cosci-composer-bg)"
    textColor: "var(--cosci-fg)"
    rounded: 2rem

  # Home recents card — the one card family that carries a real shadow
  # (reference .card values; the shadow is identical in both themes and does
  # NOT change on hover — hover swaps the fill to surface-container-low)
  recent-card:
    backgroundColor: "var(--cosci-recent-card-bg)"
    textColor: "var(--cosci-recent-card-text)"
    rounded: 0.75rem
    padding: 1rem
    shadow: "0 1px 2px rgb(0 0 0 / 15%), 0 2px 10px rgb(0 0 0 / 10%)"

  # Setup document sheet (plan spec grid + option cards + blue buttons)
  setup-document:
    backgroundColor: "var(--cosci-setup-doc-bg)"
    textColor: "var(--cosci-fg)"
    rounded: "{rounded.2xl}"

  # User chat bubble — asymmetric corners (26px with a 4px top-right notch)
  user-bubble:
    backgroundColor: "var(--cosci-user-bubble-bg)"
    textColor: "var(--cosci-fg)"
    rounded: 26px

  # Setup-surface radio option card (ring+dot marker, no selected tint)
  option-card:
    backgroundColor: "var(--cosci-option-bg)"
    textColor: "var(--cosci-fg)"
    rounded: 0.65rem
    padding: "0.85rem 0.95rem"

  # Canonical tooltip (data-tooltip + ucs-tooltip-*) — inverse surface
  # (dark chip in light mode; dark mode inverts to #e3e3e3 / #303030)
  tooltip:
    backgroundColor: "#303030"
    textColor: "#f2f2f2"
    rounded: 0.45rem
    padding: "0.34rem 0.52rem"

  # Empty-state placeholder box (workbench/components/empty_state.tsx)
  empty-state:
    backgroundColor: transparent
    textColor: "{colors.on-surface-variant}"
    rounded: "{rounded.base}"
    padding: 24px

  # Skeleton loader (.wb-skeleton) — shimmer over --cosci-skeleton-bg
  # (light #f0f4f9 / dark #282a2c)
  skeleton:
    backgroundColor: "var(--cosci-skeleton-bg)"
    rounded: "{rounded.md}"
---

# Co-Scientist

## Overview

Co-Scientist is a Gemini Enterprise-style workbench for multi-agent idea development. The live surface is a single-page workbench: a chat workspace at `/` (greeting, composer, recents) and at `/chats/:id` for a reopened session, a tabbed run detail at `/runs/:id/:tab` (Goal Details, Learning, Research Overview, All Ideas) a shared read-only goal report at `/shared/:token`, and a researcher-access page at `/access`. The earlier public surface — the `/about` landing page, `/runs` dashboard, demo pages — was deliberately removed; do not reintroduce or style for it. The one exception is the **landing page under the chat home** (see Landing page): the home still opens on the chat, and the landing page sits below it, one scroll away.

The visual language is **precise, neutral, and data-forward** — more Google product workspace than consumer app. Whitespace is generous but purposeful. Color is used sparingly and always semantically: teal/blue accents for primary actions, tonal containers for states, semantic tones for run outcomes. The palette adapts fluidly between light and dark modes through Material Design 3 dynamic color, not manual dark-mode overrides.

The design personality is calm competence. Typography is confident and quiet — display headings sit at weight 400, not bold. Rounded corners are present but not playful. Animation is brief and functional — a global motion baseline eases every interactive color/shadow change over 140ms so nothing snaps, plus a 300ms entrance fade on the home stage, a pulse on live-run indicators, and shimmer on skeleton loaders (see Motion baseline).

## Colors

The UI runs **two deliberately separate palettes**, and knowing which is which is essential before changing any color:

1. **MD3 dynamic palette** (`--md-sys-color-*`, bridged to `--color-th-*`) — derived at runtime from the `#1A6B6B` seed via `themeFromSourceColor`. Used for **data and semantic UI**: run activity tones, error/success states, the live-run pulse dot, primary actions. Its neutrals are intentionally *tinted toward the seed* by the MD3 tonal algorithm.
2. **Gemini product palette** (`--cosci-*`, in `reference_surface.css`) — the **MD3 sys colors the live Gemini Enterprise product actually uses** (`#1f1f1f` on-surface ink, `#444746` on-surface-variant, `#747775` outline text, `#c4c7c5` outline-variant borders, `#f0f4f9` surface-container, `#0b57d0` primary blue), measured from the running product in July 2026 (the capture lived at `references/ui-ux/idea-generator/live-capture-2026-07/` and has since been deleted; read it out of git history). Used for the **shell, home, and chat/setup surfaces** (rail, composer, recents, step timeline, setup document, buttons, settings dialog, ideas tab). These neutrals carry a *faint warm/green cast* — the product tints its neutrals toward its own seed, exactly like an MD3 neutral-variant ramp. (An earlier iteration used the classic blue-grey Google ramp — `#5f6368`/`#dadce0`/`#202124` — believing it was "more 1:1 with Google"; the live product disproved that.) They stay **separate** from our own `--md-sys-color-*` tokens so the data surfaces (teal seed) and the shell (product blue) can diverge on hue, not so the shell can use a different grey family. Each `--cosci-*` token has its own light/dark value (many share a light value but diverge in dark), so they cannot be collapsed by light-mode hex.

### Semantic component tokens

The `--cosci-*` palette extends beyond raw colors into a **semantic component token layer**, which lives in its own file, `styles/component_tokens.css`. Every themed component surface — logs/diagnostics, danger alerts, attachment cards, toasts, radio option cards, buttons, connector toggles, chat bubbles, the setup document — is defined **once per mode** as a token pair (light values in `:root`, dark values in `:root[data-theme="dark"]`). Components reference the token and carry **no `dark:` variants**; a surface's light/dark appearance lives in one place. Never write an inline `dark:[#hex]` override in a component — add or extend a token pair instead.

Where possible, semantic tokens **alias baseline tokens** rather than introducing bespoke hex: the Logs system (`--cosci-logs-*`) derives every value from the step-dot accent and the neutral scale (via `var()` and `color-mix()`), so it re-themes for free with no dark block of its own. Prefer aliasing when a new surface is "the same color as X"; reserve new hex pairs for genuinely new surfaces.

The raw-color/palette files split by role: `reference_surface.css` holds the Gemini product palette and the ideas-surface (`--cosci-idea-*`) tokens; `component_tokens.css` holds the semantic component tokens above; `shell_surface.css` / `home_surface.css` hold the shell and home *layout* rules that consume them. The import order in `styles/surfaces.css` is `reference_surface → component_tokens → shell* → home* → tooltips` (the shell and home sheets are each split into sequential parts), so component tokens can alias palette tokens defined before them.

The mode-dependent **accent** is worth internalizing: light mode accents in teal — the composer submit uses `--cosci-teal` (`#1A6B6B`) while everything else accented uses the deeper product teal `#238a84` via `--cosci-accent`; dark mode swaps all of those roles (accent, composer submit) to the mint accent `--cosci-green`, which itself darkens from `#7fd7bf` to `#68d0c0` in dark mode. Components get this for free by using the role tokens (`--cosci-accent`/`--cosci-accent-fg`, `--cosci-composer-submit`), never the raw teal/green. `--cosci-step-dot-*` aliases the accent and belongs to the home step circle alone, so its treatment can change without repainting every accented surface.

The **step timeline is a deliberate green divergence** from the reference (whose step dots are purple70 `#c597ff`, line `#b9a9d7`): we use our own brand greens — light dot `#238a84` with a near-white `#f2f2f2` number, dark dot mint (`#68d0c0`) with a near-black `#131314` number; the connecting line blends the accent with the neutral outline (`color-mix(in srgb, #238a84 38%, #c4c7c5)`). The home greeting is **center-aligned** under the flask mark and the reference's agent-name eyebrow above it is omitted — both deliberate divergences. The one gradient surface in the app is the **started-session card** (teal gradient, brighter in dark mode, defined in `reference_surface.css`).

### Tailwind utilities

Both palettes are registered as named Tailwind utilities in `theme_tokens.css`'s `@theme` block (imported by `index.css`): the MD3 bridge as `th-*` (`bg-th-card`, `text-th-muted-fg`) and the Gemini palette as `cosci-*` (`text-cosci-fg`, `bg-cosci-panel`, `border-cosci-border`) via `--color-cosci-*` entries that mirror the underlying tokens. **Every `--cosci-*` token referenced from a component is registered** — the semantic component tokens (`--cosci-btn-*`, `--cosci-option-*`, `--cosci-logs-*`, `--cosci-danger-*`, `--cosci-attach-*`, `--cosci-toggle-*`, …) and the ideas-surface tokens (`--cosci-idea-*`) all have `--color-cosci-*` mirrors. **Use the named utility; do not write arbitrary `[var(--cosci-*)]` classes.** The one legitimate arbitrary use is when the token is embedded inside a larger CSS value that isn't a plain color slot — e.g. the option marker's `bg-[radial-gradient(circle,var(--cosci-option-marker-on)…)]`.

The MD3-palette semantics below apply to the data/semantic surfaces:

- **Primary:** Co-Scientist teal used sparingly for semantic emphasis: the live-run pulse dot, the latest activity-row icon disc, and the rare MD3 filled button (error-boundary reload). Never used decoratively.
- **Surface / surface-container-low:** Tonal card backgrounds for data containers. Never pure white; always tinted by the seed.
- **On-surface-variant (#3F4949):** Secondary/helper text on MD3 surfaces — metadata, helper text, empty states.
- **Outline-variant (#BEC9C9):** The default 1px border for MD3-surface boxes (e.g. `EmptyState`). Borders never use a raw color — always this token.
- **Error / error-container:** Reserved strictly for failed/blocked run states and form validation. Not used for warnings or info.
- **Success, Warning, Info, Link:** Hardcoded semantic extras with no MD3 counterpart — light values in `theme_tokens.css`, each with an explicit dark override in `index.css`'s `:root[data-theme="dark"]`. Success maps to completed-run activity tones; **warning is the safety-screening activity tone** on run detail. Info and link are currently defined but unreferenced — reserved, not dead; remove only with a deliberate decision.

Run-detail **activity tones** are the run-status color system (there is no status-pill component): `text-th-warning` for safety screening, `text-th-success` for completion, `text-th-primary` for supervisor activity, `text-cosci-muted` for the rest, with Tailwind's `animate-pulse` on the live row.

Dark mode: `applyMd3Theme(true)` regenerates all `--md-sys-color-*` tokens automatically. Theme choice is a **three-way mode** (System / Light / Dark) held in `theme_context.tsx` (`localStorage` key `cosci-theme`), with live OS-scheme tracking in System mode; the setting is exposed as a segmented control in the settings menu (see Components).

## Typography

Two faces from one family cover every typographic role — this split matches the live product:

- **Google Sans** — the **display face** (`--font-gsans`, Tailwind `font-gsans`, MD3 `--md-ref-typeface-brand`). Used for the home greeting, goal-report document headings (H1/H2), settings dialog and card titles, and the product wordmark.
- **Google Sans Text** — the **plain face** (`--font-gsans-text`, `--md-ref-typeface-plain`) and the `:root` default. Everything else: chat turns, body copy, buttons, chips, labels, metadata.

Both are **self-hosted woff2** at weights 400/500/700 — Google Sans vendored from `@fontsource/google-sans`, Google Sans Text from local files in `src/assets/fonts/` — declared via `@font-face` in `index.css` with `font-display: swap`. No CDN requests; `system-ui, sans-serif` is a render-failure fallback only.

- **Display (36–45px fluid / weight 400):** The home greeting only — `clamp(2.25rem, 3.4vw, 2.8125rem)`, line-height 1.156, center-aligned. Note the weight: display text is *regular*, not bold.
- **Headline-lg (32px / 400) and Headline-md (28px / 400):** The goal-report document's own H2/H3 (`run_detail_document.tsx`; its `<h1>` is the shell titlebar, at 1.2rem) — headline-lg also covers the ideas detail-pane headings. Google Sans, regular weight, generous leading.
- **Title-lg / md / sm (22 / 20 / 16.8px, 500):** Settings dialog title, product wordmark, settings card titles.
- **Setup-title (23.2px / 600) and Setup-section (18.9px / 700):** The setup document's plan-sheet title and section headings — Google Sans Text, the one place heavier weights appear.
- **Body-md (16px / 400):** Default readable copy.
- **Body-sm (14px / 400):** Card metadata, recents meta lines, helper text.
- **Label-lg (14px / 500):** Button labels, nav links, tab labels.
- **Label-md (12px / 500):** Chip text (Elo, rank, unverified), badges, small metadata.

**Icons:** Material Symbols **Rounded** exclusively — the public cut of Google Symbols ROND, which the live Gemini Enterprise product uses — delivered through the first-party `<Icon name="…">` component (`src/components/icon.tsx`). The glyphs are authentic weight-400 **filled paths** (never stroked), inlined as SVG (generated by `scripts/generate_icons.mjs` from `@material-symbols/svg-400/rounded`) so the set stays tree-shakeable, prerender-safe, and free of font FOUT. Icons inherit `currentColor` and size to `1em`, so set the icon's color and `font-size` on the element. Never use the outlined or sharp variants, and never hand-author glyph paths — add the icon to the generator and re-run it.

## Layout & Spacing

The **MD3 data surfaces** follow an **8px base grid**. All spacing values on those surfaces are multiples of 8px; the one exception is `xs: 4px` for micro-adjustments inside dense components.

- **App shell:** `.ucs-app-shell` is a two-column grid — collapsible nav rail plus workspace — whose `grid-template-columns` animates over 240ms on rail toggle. The workspace panel is inset with a rounded top-left corner (`border-top-left-radius: 1.85rem`). Below the mobile breakpoint the rail becomes an off-canvas drawer with a `.ucs-scrim` overlay.
- **Header:** `.ucs-header-action-bar` is sticky, 64px min-height (the shell reserves 72px), `padding-inline: 1.625rem`, solid `--cosci-surface-bg` fill.
- **Run detail content:** the document column is `w-[min(100% - 3rem, 58rem)]` (928px) inside the workspace, shared by the skeleton and toast; the in-flight view uses `max-w-4xl` (896px). The four-tab bar spans `grid-cols-4`.
- **Home stage:** a single centered column (greeting ≤ `34.375rem` wide) laid out as a grid whose **empty spacer rows are the shrinkable tracks** — under vertical pressure the gaps compress instead of the composer or stepper colliding. Vertical rhythm uses `clamp()` values so the stage breathes with the viewport. Preserve this spacer-track scheme when editing the home grid; fixed margins reintroduce overlap.
- **Chat column:** user bubbles cap near `31rem`; model turns run the full column width.

**Reference-matched surfaces do not use the 8px grid.** The Gemini shell, home, and chat/setup surfaces (`chat_setup_classes.ts`, `chat_home_classes.ts` in `src/workbench/pages/`, and the `reference-*` / `ucs-*` CSS) reproduce the Gemini product's own measurements, which are **literal rem/px values copied from the reference** — `[0.92rem]`, `[1.18rem]`, `[1.45rem]`, `[2.6rem]` button heights, `1.625rem` header padding, and so on. These are deliberate, not drift: snapping them to the 8px grid would break the pixel-match with Gemini. This is the same reference-vs-system split as border-radius (see Shapes) and the recents-card shadow (see Elevation & Depth). Rule of thumb: **an MD3 data surface uses grid multiples; a `reference-*` / setup / home surface uses the reference's literal value.** When adding to a reference surface, copy the reference's measurement rather than rounding it to the grid; when building a new MD3 data surface, stay on the grid.

There is **no global margin reset**. The markdown-rendered Goal Report depends on default element margins for paragraph rhythm; a `* { margin: 0 }` preflight collapses it (16px → 0 between paragraphs). Zero out margins per-component where needed.

## Elevation & Depth

Depth is achieved primarily through **tonal layers** — page content (cards, panels, inputs) never uses drop shadows.

- **Background (Level 0):** the page body — `--cosci-bg` on shell surfaces, `surface` on MD3 surfaces.
- **Cards / containers (Level 1):** one tonal step up (`--cosci-panel` / `surface-container-low`), with a 1px `outline-variant`-class border where separation is needed.
- **Hover (Level 2):** neutral hover washes (`--cosci-hover`) or `secondary-container` on MD3 surfaces, applied via `transition-colors`. No border change on hover.
- **Header:** a **solid** `--cosci-surface-bg` sticky bar — no shadow, no backdrop blur. It separates from content by color continuity, not depth.
- **Floating overlays:** menus, popovers, dialogs, and toasts *do* carry MD3 elevation, applied with the `--md-elevation-1/2/3` shadow tokens (defined in `index.css`, with lifted opacities in dark mode). Popovers and the connectors menu use level 2; toasts (`.reference-toast`, `.reference-report-toast`) use level 3. This is the one place shadow is correct — a surface detached from the page needs to read as floating.
- **Recents cards (the one card exception):** `.reference-recent-card` on the home surface carries the reference's exact two-layer `.card` shadow — `0 1px 2px rgb(0 0 0 / 15%), 0 2px 10px rgb(0 0 0 / 10%)` — **identical in both themes and constant on hover** (hover swaps the fill to `--cosci-recent-card-hover-bg` and eases `background-color` over 160ms; elevation never changes). Do not extend this treatment to other cards — it is a deliberate reference-matching exception, not a precedent.
- **Home composer (the one input exception):** the reference casts `0 2px 12px -2px` in surface-container-high under the composer in light mode and **no shadow in dark**; this lives on the `--cosci-composer-shadow` token (light: the shadow; dark: `none`), applied by `.reference-composer`. The dark composer is also borderless (`--cosci-composer-border: transparent`).

Never add `box-shadow` to any other card, panel, or input. Borders and tonal layers provide all the separation those need. Reserve the `--md-elevation-*` tokens strictly for surfaces that float above the page.

## Shapes

The shape language is **restrained and consistent**, but it splits along the same line as the color system: MD3 data surfaces follow a strict three-radius scale, while the Gemini shell/home/chat surfaces reproduce the reference product's geometry exactly.

**MD3 data surfaces** — three radii cover all cases:

- **`rounded-md` (6px):** Error/alert boxes, data blocks, skeletons. The default for any "block" that contains data. (The bare `rounded` utility — Tailwind's 8px `--radius` — is the other block radius in use, on `EmptyState` and similar.)
- **`rounded-xl` (12px):** Containers with more visual weight or interactive importance.
- **`rounded-full` (9999px):** All buttons (MD3 buttons are pill-shaped), chips, the live-dot indicator. Used for anything that is interactive or badge-like.

Never mix `rounded-xl` and `rounded-full` on the same element. Do not use `rounded-2xl` or larger on data surfaces.

**Gemini shell/home/chat surfaces** — radii match the reference, not the scale:

- **`rounded-[2rem]` (32px):** The composer.
- **`1.85rem`:** The workspace panel's top-left corner.
- **User bubbles:** asymmetric — `26px` on three corners with a `4px` notch at the top-right (`rounded-tl-[26px] rounded-tr-[4px] rounded-br-[26px] rounded-bl-[26px]`).
- **`rounded-2xl` (16px):** The setup document, started-session card, composer image previews.
- **`0.75rem` (12px):** Recents cards.
- **`0.65rem` (10.4px):** Radio option cards.
- **`0.45rem`:** Tooltips.
- **`rounded-full`:** All pills and icon buttons, same as everywhere else.

These values are copied from the Gemini product and should not be "normalized" onto the three-radius scale — matching the reference wins. New shell components take their radius from the closest reference component, not from the MD3 scale.

## Components

> **Architecture note.** Components are first-party React elements styled to the Material Design 3 spec — not the `@material/web` custom-element library. MD3 is followed as a *design language* (dynamic color via `material-color-utilities`, the type/shape/elevation scales, and state layers), which is how Google's own flagship products are built. Keep components as semantic HTML (`<button>`, `<nav>`, `role="menu"`) styled with the shared tokens below; do not reintroduce `md-*` custom elements.

### Class-name prefixes

Bespoke **styled** CSS class names (as opposed to Tailwind utilities) use **exactly two prefixes**, split by origin. New CSS classes must take one of them; do not invent a third family or revive the retired ones (`google-*`, `gemini-*`, `cosci-*` as a *class* prefix, `wb-*` beyond the stray below).

- **`ucs-*`** — app **shell chrome** the reference doesn't dictate: the app shell grid, nav rail items, header bar, chat list, popovers, the settings menu/dialog, the landing page under the chat home (`ucs-landing-*`), and the canonical tooltip system (`ucs-tooltip-*`).
- **`reference-*`** — surfaces that reproduce a **specific Gemini reference** screen 1:1: the composer, recents cards, step timeline, chat bubbles, setup document, spec grid, option cards, connectors menu, report tabs/toast, workspace-main.

Two intentional strays remain: `wb-skeleton` (the one surviving `wb-*` utility) and `md-state` / `md-elevation-*` (MD3 primitives). The Ideas tab additionally uses bare `idea-*` class names (`idea-split-shell`, `idea-rank-row`, `idea-detail-pane`, …) as **unstyled structural/test markers** — they carry no CSS rules (styling comes from Tailwind `cosci-idea-*` utilities) and must stay that way; if an `idea-*` class ever needs a stylesheet rule, rename it into one of the two families instead. Everything else is a Tailwind utility. Note the `--cosci-*` **custom-property** prefix is unrelated to class names — it's the token namespace (see Colors) and stays.

### Interaction states

Every interactive element gets an MD3 **state layer** — a translucent `currentColor` overlay that fades in on hover (8%), focus (10%), and press (10%) over ~120ms. Use the reusable `.md-state` utility (`index.css`), which paints the layer beneath the element's content via a `::before`-safe `::after` at `z-index:-1`. Elements that already use `::after` (e.g. the run-detail tabs, which use it for the selected underline) get an equivalent `::before` state layer. Respect `prefers-reduced-motion`.

### Motion baseline

**Nothing snaps.** A global baseline in `index.css` transitions `background-color`, `border-color`, `color`, `box-shadow`, and `opacity` over **140ms** with the MD3 standard easing (`cubic-bezier(0.2, 0, 0, 1)`) on every `button`, `a`, `summary`, `[role="button"]`, `[role="tab"]`, `input`, `select`, and `textarea`. Component-specific transitions (higher specificity) still win where set — e.g. recents cards ease `background-color` over 160ms, the sidebar rail animates `grid-template-columns` over 240ms with nav labels fading/collapsing in sync (opacity 180ms / max-width 240ms).

The motion budget by tier: **micro-interactions ≤ 200ms** (the 140ms baseline, the 120ms state layer); **structural motion ≤ 240ms** (the sidebar rail); **entrance fades at 300ms** (`reference-fade-in`, 0.3s ease-in-out, on the home stage) — the ceiling; and the run-step **spinner** loops at 0.8s. Do not add anything slower than 300ms. The landing page under the chat home is the one exemption (see Landing page); its motion never reaches the workbench above it.

Two guardrails:

- **Theme switching is exempt.** `theme_context.tsx` adds a `.theme-switching` class across a double `requestAnimationFrame` on mode toggle, which force-disables all transitions so the entire page doesn't animate through the palette swap.
- **`prefers-reduced-motion: reduce` disables every transition** — the baseline, the sidebar, the state layers, and any component-specific motion. Any new animation must include this media-query escape.

### Buttons

Buttons are pill-shaped (`rounded-full`) semantic `<button>` elements following MD3 button roles. One filled primary action per screen; secondary actions are outlined or text-styled.

**Setup/chat-surface buttons** (`--cosci-btn-*` tokens) — the primary button system on the live surface. The Gemini setup flow uses Google's own button colors, not the MD3 teal:

- **Primary (filled)** — MD3 `md-filled-button`: Google blue `#0b57d0` with white label in light mode; in dark mode the MD3 inversion — primary `#a8c7fa` fill with on-primary `#062e6f` label. Used for "Start" on the setup document.
- **Outline** — MD3 `md-outlined-button`: outline-colored border (`#747775` light / `#8e918f` dark) with a primary-colored label (`#0b57d0` light / `#a8c7fa` dark), transparent fill, primary-tinted 8% hover wash. Used for follow-up actions ("View session details").
- **Secondary** — neutral gray border and ink label, gray hover. Used for "Cancel"-grade actions.
- All three share the pill geometry (`min-h-[2.6rem]`, `px-[1.45rem]`) and a **disabled trio** (`--cosci-btn-disabled-border/bg/fg`).

**MD3 filled button** (teal `primary` / `on-primary`, 40px, `px-5`) survives only where the shell tokens aren't loaded or don't apply — e.g. the error-boundary "Reload" action. Keep it rare.

**Icon buttons** — icon-only actions (header actions, Logs, composer source buttons, message actions). Circular, transparent, state layer on hover/press. Icon-button hovers are always **neutral gray** (`--cosci-hover` / `bg-cosci-hover`), never tinted.

The composer submit button is none of these systems — it uses the mode-dependent accent (`--cosci-composer-submit`: teal in light, mint in dark).

### Composer

The research-goal composer (`.reference-composer`) is a growing textarea inside a `rounded-[2rem]` shell with inline attachment, connector, and submit controls, plus an overlay gradient fade where content scrolls beneath it. Attachments render as `--cosci-attach-*` cards (image previews stay square with the filename in a tooltip). The **connectors menu** (`.reference-connectors-menu`, MD3 elevation-2) lists literature sources — plus the **web search connector**, shown only when the backend advertises the tool — with per-connector **toggle switches** themed by the `--cosci-toggle-on/off-*` token pairs. The composer stays usable while the agent is answering.

### Chat & setup surface

The session chat column (`chat_setup_classes.ts` / `chat_home_classes.ts`, under `src/workbench/pages/`) is a Gemini-style conversation:

- **User bubbles** — asymmetric 26px/4px corners (see Shapes), `--cosci-user-bubble-bg` (soft blue-gray light / neutral dark), max-width ~31rem, right-aligned. **Model turns are bubble-less** — plain text on the workspace background at full column width.
- **Message actions** (Copy/Edit prompt) — icon buttons revealed on hover/focus of the turn, neutral-gray hover, no outline ring.
- **Setup document** — a `rounded-2xl` `--cosci-setup-doc-bg` sheet containing the plan spec grid, option-card radio groups, and the blue setup buttons.
- **Started-session card** — a `rounded-2xl` teal **gradient** card (the one gradient surface in the app, defined in `reference_surface.css` with a brighter dark-mode variant), white text, with an outlined-white "Open" pill.

### Home stage & recents

The home surface centers the flask mark and greeting (display type, weight 400) above a **three-step onboarding timeline** (the green step dots — see Colors), suggestion cards with hover-preview bubbles, and the composer. The **recents panel** lists `RecentRunCard`s (the shadowed reference cards — see Elevation & Depth) with a bottom mask fade and a dashed empty-state card. A running card shows the run's real phase as a step flow labeled "In Progress", with a 0.8s `reference-run-step-spin` spinner on the active step. Run status elsewhere renders as **plain text tones, not pills** — there is no status-pill component.

### Landing page

The chat home (`/`) opens exactly as before. One gray line under the composer (`.reference-home-scroll-hint`, "Scroll to see how Co-Scientist works" with a bobbing chevron) points down to a **landing page** rendered below the home stage (`home_landing.tsx`, lazy-loaded so the home's first paint never waits on it). While it is mounted, `.ucs-page--home` scrolls and the stage keeps exactly one screen (`home_landing.css`); the conversation view never mounts it.

It is the app's one **editorial surface**, modeled on Google's product and model pages (DeepMind model pages, Google Labs, NotebookLM), so it deliberately steps outside the workbench rules below the fold — and only there:

- **Type:** only the app's own faces: **Google Sans** for display (the wordmark and section headings at large sizes, regular weight, near-zero tracking) and **Google Sans Text** for everything else, labels and figures included. No other family, and no glyph outside their latin subset (so no `→`), since a missing glyph falls back to a system font.
- **Shape:** Material 3 Expressive shapes (cookie, flower, clover, sunny, gem, pill), sampled at one point count so they morph (`home_landing_shapes.ts`); cards and media at 24–48px radii; pills for every control.
- **Color:** landing-scoped tokens (`--l-*` on `.ucs-landing`) with tonal container pairs (`--l-c-*` fill / `--l-o-*` ink) in teal, blue, green, yellow, red, redefined under `:root[data-theme='dark']`. The Google four-color set appears only as data (tier cycles).
- **Motion:** allowed past the 300ms budget, because it is content rather than feedback: the Overview's run stages lighting in order, a sources marquee, line draw-in on the Elo chart, shape morphs on hover (agent and safety cards), and the sliding selection pill on the section rail and tier picker. Nothing that carries information advances on its own: the system diagram highlights the agent you hover or tap, and the tournament tree plays one round per click. Every one has a `prefers-reduced-motion` path that renders the settled frame.
- **Facts:** every number is the product's own — tiers mirror `RUN_TIER_DEFAULTS` (pinned by `app/tests/test_landing_tiers.py`) and the starting Elo mirrors `INITIAL_ELO_RATING`. Simulations are labeled as simulations.

Sections, in order: Overview (one run end to end: what you write, what the agents do, what you get), How it works (a system diagram after the paper's architecture figure, plus agent cards), Tournament (a tree of example debates with real Elo updates, played round by round with a button, an Elo chart, the podium), Evidence (claim verdicts and the sources marquee), Safety, Tiers (interactive pool), a closing call to action with the flask render that scrolls back up and focuses the composer, then the full-width FAQ, every answer closed until opened. There is no footer, and no horizontal rules above the hero or under the rail.

### Ideas tab

The All Ideas view (`ideas_tab.tsx` + `ideas_detail_pane.tsx`) is a desktop **split pane** (rank list left, detail pane right) that collapses to a master-detail flow on mobile. Rows carry Elo and rank chips plus an "unverified" caution chip; every surface in the tab is themed by the `--cosci-idea-*` token family in `reference_surface.css`. Detail-pane section headings use the display face at `2rem`.

### Settings

The rail's settings entry opens a `ucs-*` **menu popover** (`.ucs-popover--menu`, MD3 elevation-2) containing the **three-way theme segmented control** (`.ucs-theme-segment` / `.ucs-theme-button`: System / Light / Dark), and a centered **settings dialog** (`.ucs-settings-dialog`) with a section nav, card-based panels, and field inputs, in two sections: Appearance and Model. There is no Help section; the product FAQ lives on the landing page under the chat home (`home_landing_content.ts`, reachable at `/#faq`). Saving is silent -- the field shows what it stored. Dialog and card titles use the display face (title-lg / title-sm). New preference UI belongs here, not in ad-hoc popovers.

### Tabs (Run Detail)

A first-party `<nav>` of `<button>` tabs (`.reference-report-tabs`, `grid-cols-4`) for the run views: Goal Details, Learning, Research Overview, All Ideas. The active tab is `primary`-colored with a bottom underline drawn via `::after`; hover/focus paints an MD3 state layer via `::before` (see Interaction states). Tab content panels are full-width below the tab bar.

### Logs / Diagnostics

A header **Logs pill** (filled with the mode accent — teal in light, mint in dark — plus an entry-count badge) opens a floating **popover panel** (`ucs-popover--logs`, MD3 elevation) rendering the **persisted app-wide log** (the backend's `app_logs` store): the newest 100 records with consecutive `#N` numbering, identical on every route, with a Total chip carrying the filtered-stream size. Clear deletes server-side; Copy writes a context preamble followed by the newest 100 entries as JSON. Every color in the panel is a `--cosci-logs-*` token that **aliases a baseline token** — the accent from the step-dot pair, surfaces/borders/text from the neutral scale — so the panel re-themes with no dark overrides of its own. Status chips are filled (accent for ok, danger pair for errors); Clear/Copy actions are outlined in the accent; log messages render as plain text in monospace on a `--cosci-logs-panel-bg` code block.

### Tooltips

One canonical tooltip system: set `data-tooltip="…"` plus the `.ucs-tooltip-anchor` class — build the class list with `tooltipClassNames()` in `tooltip.ts` rather than hand-assembling modifiers. The tooltip is an **inverted surface** — dark chip (`#303030`, MD3 inverse-surface) with `#f2f2f2` text in light mode, light chip (`#e3e3e3`) with `#303030` text in dark mode — with a small shadow, `0.45rem` radius, 0.78rem medium text, and a subtle scale/translate entrance on hover/focus-visible. Placement modifiers: `.ucs-tooltip-top/bottom/left/right`, alignment `.ucs-tooltip-align-start/end`, and `.ucs-tooltip-wrap` for multi-line content. Never hand-roll a bespoke tooltip; new affordances must use this system.

**Cascade, not `!important`.** `tooltips.css` is **unlayered author CSS** imported after Tailwind's `@layer utilities`, so its rules already outrank utility classes — an `overflow-hidden` utility on an anchor can't clip the tooltip, and no declaration needs `!important`. This is deliberate and load-bearing: keep the file unlayered rather than reaching for `!important` to win a specificity fight. The placement/alignment modifiers share the base selector's specificity and rely on source order (they appear after the base rule).

### Scrollbars

Scrollbars are themed globally (`index.css`) as a **trackless floating thumb**, Google style: no channel behind the thumb, just a rounded gray pill (`#bdc1c6` light / `#444746` dark; hover darkens to `#747775` / lightens to `#8e918f`) inset by a 3px transparent border inside a 14px hit area. Implementation note: the styling deliberately uses the `::-webkit-scrollbar` pseudos and does **not** set the standard `scrollbar-width` / `scrollbar-color` properties — in Chromium those suppress the webkit pseudos.

### Radio option cards

The setup flow's Focus/Tier pickers are card-shaped radio groups (`--cosci-option-*` tokens): a transparent-bordered card that gains a border and tinted background on hover/focus-within only. **Selection is communicated solely by the radio marker** — a Material-style ring with a centered inner dot (radial-gradient), gray when idle, blue when selected. Selected cards do *not* tint their background.

### Progress & Loading

- **Skeleton loaders:** `.wb-skeleton` — neutral gray shimmer animation, colored by the `--cosci-skeleton-bg` token pair (light `#f0f4f9` / dark `#282a2c`) so it themes like everything else rather than via a hardcoded hex. Used while API calls resolve.
- **Live indicators:** the run pulse dot (`animate-ping` + `bg-th-primary`) and the pulsing latest-activity icon disc on run detail; the 0.8s run-step spinner on home recents.

### Empty states

Empty placeholders use the shared `EmptyState` component (`workbench/components/empty_state.tsx`): a centered `rounded` bordered box, `outline-variant` border, `on-surface-variant` text. Don't inline one-off empty-state markup in views.

## Do's and Don'ts

- **Do** use the setup button trio (`--cosci-btn-*`) for actions on shell/chat surfaces, with one filled primary per screen; reserve the MD3 teal filled button for MD3-only contexts like the error boundary.
- **Do** use `on-surface-variant` / `cosci-muted` for all secondary/helper text. Never use `opacity: 0.5` on foreground text.
- **Do** let `applyMd3Theme()` generate color tokens. Never hardcode MD3 palette values like `--md-sys-color-primary`.
- **Do** use Material Symbols Rounded via the `<Icon>` component. Size it with `font-size` (icons render at `1em`) and color it with `color` (icons use `currentColor`).
- **Do** keep motion inside the budget: micro-interactions ≤ 200ms, structural ≤ 240ms, entrance fades ≤ 300ms (`reference-fade-in`), every one with the `prefers-reduced-motion` escape.
- **Do** theme new component surfaces with paired light/dark `--cosci-*` tokens in `component_tokens.css`. Never write inline `dark:[#hex]` overrides in components.
- **Do** alias existing baseline tokens (via `var()` / `color-mix()`) when a new surface should match an existing color, as the Logs tokens do.
- **Do** register every component-referenced `--cosci-*` token as a `--color-cosci-*` utility and use the named class (`bg-cosci-btn-primary-bg`). Reserve arbitrary `[var(--cosci-*)]` for tokens embedded in a non-color value (e.g. a gradient).
- **Do** give new bespoke styled CSS classes a `ucs-*` (shell chrome) or `reference-*` (Gemini-reference surface) prefix. Don't invent a third family or revive `google-*` / `gemini-*` / `wb-*`; keep the Ideas tab's bare `idea-*` classes as unstyled markers only.
- **Do** use the `data-tooltip` + `ucs-tooltip-*` system for any new tooltip, and keep `tooltips.css` unlayered + imported last so it wins without `!important`.
- **Don't** add `box-shadow` to cards, panels, or inputs (sole exceptions: the home recents cards and the light-mode composer, both matching the Gemini reference). Tonal layers and borders are sufficient everywhere else.
- **Don't** use `rounded-2xl` or larger on MD3 data surfaces. The three-size system (md / xl / full) covers those; Gemini shell/chat surfaces copy the reference geometry instead (see Shapes).
- **Don't** snap the arbitrary rem values on reference-matched surfaces (setup / home / `reference-*`) onto the 8px grid — they are literal reference measurements. Conversely, don't introduce off-grid values on MD3 data surfaces (see Layout & Spacing).
- **Don't** add a global margin reset (`* { margin: 0 }` or a preflight that includes one) — the markdown Goal Report depends on default margins. Zero margins per-component.
- **Don't** fold the `--cosci-*` product palette into the MD3 tokens, and don't use raw `--cosci-teal` / `--cosci-green` directly — use the accent role tokens (`--cosci-accent`, `--cosci-composer-submit`, `--cosci-logo-color`) so light/dark swap correctly.
- **Don't** give any element a `prefers-reduced-motion`-exempt animation; every transition must have the reduce escape.
- **Don't** use more than two font weights on a single card or panel, and don't bold display headings — Google Sans display roles are weight 400.
- **Don't** reintroduce status pills, phase-colored progress segments, dashboards, or marketing surfaces beyond the one landing page under the chat home — run status is communicated through activity text tones and the recents step flow. (The Logs panel's count chips are tally chips, not run-status pills; they are fine.)
- **Don't** introduce new semantic colors without both halves of the pair — the light value in `theme_tokens.css` and a hardcoded dark override in `index.css`.
