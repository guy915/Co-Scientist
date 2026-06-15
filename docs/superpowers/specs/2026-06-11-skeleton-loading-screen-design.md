# Skeleton Loading Screen Design

**Date:** 2026-06-11
**Status:** Approved

## Problem

`<div id="root">` is empty before React mounts. Users see a blank white (or dark) flash for ~100ms. Previously this contained prerender content that was moved to `<noscript>` to fix a loading flash — leaving nothing visible during mount.

## Goal

Replace the blank flash with an animated shimmer skeleton that approximates the landing page layout above the fold, so the page feels intentional from the first frame.

## Approach: Animated shimmer skeleton in `index.html`

All changes are confined to `ai-coscientist-app/frontend/index.html`. No React code changes.

### Style block (in `<head>`)

A `<style>` block defines:
- CSS custom properties scoped with `prefers-color-scheme` media queries for light/dark colors
- A single `@keyframes skeleton-shimmer` that slides a `linear-gradient` highlight left-to-right at 1.5s infinite
- Utility classes: `.sk-wrap` (full layout shell), `.sk-header`, `.sk-hero`, `.sk` (individual placeholder block)

**Colors:**
- Light: background `#FBFCFC`, shimmer gradient `#DDE8E8` → `#F0F7F7` → `#DDE8E8`
- Dark: background `#191C1C`, shimmer gradient `#252C2C` → `#2E3535` → `#252C2C`

### Skeleton HTML (inside `<div id="root">`)

Mimics the landing page above the fold:

- **Header bar:** flask icon rectangle + "Co-Scientist" text placeholder + two nav-link blocks + pill button outline on the right
- **Hero section (two columns):**
  - Left: wide 2-line heading shimmer, one narrower subtext line, two side-by-side button outlines
  - Right: large rounded rectangle for the workbench preview widget

### Cleanup

React replaces `#root` innerHTML on mount — no explicit cleanup required.

## Known limitation

Users who have manually toggled the theme (stored in `localStorage`) opposite to their OS `prefers-color-scheme` will see the wrong skeleton color for ~100ms. This is unavoidable without JavaScript and affects a small fraction of users. Not worth solving.

## Out of scope

- Skeleton for `/runs` (dashboard) or `/runs/:id` (run detail) pages
- Animation timing customization
- Matching exact MD3-generated color values (approximations are close enough for a 100ms flash)
