# Visual-fidelity diff: our app vs live Idea Generation reference

Measured July 2026 by dumping computed styles from both the live reference
(`ideaforge`) and our running app (localhost:5183) for the same elements.
Reference truth is in `reference-values.md`. Deliberate divergences (teal/green
accent instead of purple; custom text fields; composer button options;
"Co-Scientist" branding; the 4-tab report structure) are excluded — everything
below is an *unintended* drift toward off-the-shelf Google styling.

## Root cause (systematic)

Our `--cosci-*` shell palette (`reference_surface.css`) is built on the
**classic Google product ramp**, but the actual Gemini Enterprise product uses
the **MD3 sys palette**:

| Role | Ours (classic Google) | Reference (MD3) | Tilt difference |
|---|---|---|---|
| Primary text | `#202124` | `#1f1f1f` | ~same |
| Secondary text | `#3c4043` | `#444746` | ours blue-grey, ref green-grey |
| Muted text | `#5f6368` | `#747775` | ours darker+blue, ref lighter+green |
| Border | `#dadce0` | `#c4c7c5` | ours blue-grey, ref neutral |
| Panel / container | `#f1f3f4` | `#f0f4f9` | ref faint blue |
| Hover surface | `#f1f3f4` | `#e9eef6` (container-high) | ref deeper |
| Link / accent blue | `#1967d2` / `#1a73e8` | `#0b57d0` | ours brighter, ref deeper |
| Idea chip blue | `#e6f4ff` | `#e0f4ff` | ~same |
| Winning chip | bg `#d7f4d1` / **green** text `#174f2a` | bg `#beefbb` / **neutral** text `#1f1f1f` | ref darker-green bg, neutral text |

The `reference_surface.css` header comment asserts these true greys are "more
1:1 with Google" — the live product contradicts that. The product's neutrals
tilt toward its own seed (a faint warm/green cast), which is exactly what an
MD3 neutral-variant ramp does. Retuning our `--cosci-*` neutrals + blue to the
measured values fixes ~half the drift in one place.

## Home surface

| Element | Ours | Reference | Fix |
|---|---|---|---|
| Greeting | 48px/54.7 w400 `#202124` | 45px/52 w400 `#1f1f1f` | 48→45px, lh 52, color via token |
| Step circle | 32px, filled teal `#1a6b6b`, w600, text `#fff` | 30px, light purple `#c597ff`, w400, text `#f2f2f2` | see note below — size 30, weight 400 |
| Step title | 14.7px `#3c4043` | 14px `#444746` | 14px + token |
| Step body | 15.4px `#202124` | 14px `#1f1f1f` | 14px + token |
| Suggestion card | radius 16, border `#c4c7c5`, pad 14.4/16, **no hover** | radius 16, border `#c4c7c5`, pad 12, hover → `#e9eef6` | pad 12; add hover bg + transition |
| Composer | radius 27.2, border `#e0e0e0`, **no shadow** | radius 32, border `#e9eef6`, shadow `rgb(233,238,246) 0 2px 12px -2px` | radius 32; border tint; add soft shadow |
| Recents card | radius 16, shadow grey `.12/.08` `1px3px/6px14px`, border `#eef1f4` | radius 12, shadow black `.15/.10` `1px2px/2px10px`, no border | radius 12; retune shadow tighter+black; drop border |
| Meta chip (date/time) | 12.5px w600, radius 5.6, pad 6/10, `#3c4043` | 11px w500 ls .1, radius 5, pad 4/8, `#1f1f1f` | 11px/w500/ls; radius 5; pad 4/8; token |
| Winning/score chip | 10.9px w600, bg `#d7f4d1`, text `#174f2a` | 11px w500 ls .1, bg `#beefbb`, text `#1f1f1f` | 11px/w500/ls; bg `#beefbb`; neutral text; pad 4/8 |
| Recents heading | 19.5px w500 `#202124` | 16px w500 `#1f1f1f` | 16px + token |
| Recents list item | 13.4px w400 | 12px w400 ls .1 | 12px + ls |

**Step-circle note (judgment call):** the reference uses a *light pastel*
circle (purple70) with near-white text — a soft treatment. We deliberately use
green instead of purple, but we also render it as a *dark filled* teal circle,
which changes the treatment, not just the hue. Faithful-to-source would be a
light teal tint. Flagged for the owner; left as a size/weight fix only for now
(30px, w400) so the brand-fill decision stays reversible.

*Update (2026-08-16):* still the owner's call, but it is now actually cheap to
reverse. `--cosci-step-dot-bg` had quietly become the app's shared accent —
the logs and feedback popovers, the proposals focus ring and relation links,
and the logo all aliased it — so repainting the step circle would have
repainted six unrelated surfaces. Those consumers now read `--cosci-accent` /
`--cosci-accent-fg` (`styles/reference_surface.css`), and `--cosci-step-dot-*`
is the step circle's alone. Switching to a light teal tint is a two-line token
change in that file, per theme, touching nothing else.

## Ideas / report surface

| Element | Ours | Reference | Fix |
|---|---|---|---|
| Idea rank / Elo chip | 12.5px w500, bg `#e6f4ff`, pad 0 (grid) | 14px w400, bg `#e0f4ff`, radius 20, pad 4/12 | 14px/w400; bg token; pad 4/12 |
| Idea card title | 14.4px w600 | 16px w500 | 16px/w500 |
| Idea card snippet | 11.5px w400 | 12px w400 ls .1 | 12px + ls |
| Idea card (selected) | bg `#f1f8fc`, border `#8ab4f8`, radius 8, pad 14.4 | bg `#f4faff`, border `#0b57d0`, radius 10, pad 16 | bg/border tokens; radius 10; pad 16 |
| Idea card (unselected) | bg white, border `#dadce0`, radius 8 | bg transparent, border `#c4c7c5`, radius 10 | transparent bg; border token; radius 10 |
| Breadcrumb | 12.5px w600 `#3c4043`, bg `#f1f3f4`, radius 8, pad 0/7 | 11px w500 ls .1 `#1f1f1f`, bg `#f0f4f9`, radius 5, pad 4/8 | 11px/w500/ls; token; radius 5; pad 4/8 |
| Doc H2 (Goal/Overview) | **44px** (clamp) lh 49, mb 20 | 32px/40, mb 24 | 32px flat; lh 40; mb 24 |
| Doc H2 (ideas renderer) | 30.4px/35 | 32px/40 | 32px/40 (unify both doc systems) |
| Doc H3 | 21.6px (`REPORT_H3`) | 28px/36 | raise sub-heads toward 28 where they map to header-medium |
| Doc body | 16px/**27.2** (lh 1.7) | 16px/**24** (lh 1.5) | line-height 1.5 |
| Sections rail panel | bg `#f1f3f4`, radius 7.2, pad 16, width 212 | bg `#f0f4f9`, radius 10, pad 20, width 244 | token bg; radius 10; pad 20; width ~244 |
| Sections rail header | 12.5px w400 `#5f6368` | 12px w400 ls .1 `#1f1f1f` | 12px/ls; dark (not muted) |
| Sections rail links | 14.4px w600 `#1967d2` | 16px w500 `#0b57d0` | 16px/w500; blue token; looser rhythm |
| Active tab underline | `#1a73e8` | (n/a — ref has no tabs) | unify to `#0b57d0` for internal consistency |

## Motion (reference → apply where missing)

- Landing content + tournaments: `fadeIn 0.3s ease-in-out forwards`.
- Step circle: `background-color .3s ease-in-out`.
- Nav labels / chips: `opacity .125s`.
- Skeleton shimmer 2s infinite.
- Suggestion + idea rows: background-color transition on hover (~.14–.2s).
- Focus-visible: `outline 2px auto secondary; offset -1px`.

## Extracted from the saved DOM (`../home-page`, `../ideas-results`, `../session-setup`)

Read directly out of the saved `<style>` blocks (declared values, exact):

- **Greeting** (redesign `.header.header-subtitle`): `2.8125rem`/`3.25rem`
  line-height, w400, `text-align:start`, `align-self:flex-start`,
  `max-width:550px` — confirms our 45px/52 left-aligned choice to the pixel.
- **Agent chip** (redesign variant): borderless, `color:on-surface-variant`,
  16px, `align-self:flex-start`, `padding:0` — an inline icon + name, *no*
  filled avatar. Fixed ours accordingly.
- **Sections rail** (`.navigation-block`): `min-width:200px`, `margin:20px`,
  `padding:20px`, `border-radius:10px`; `ul { margin:20px 0 0 }`;
  `li+li { margin-top:24px }`; `li { color:primary; 16px; w500 }`;
  `li.active { text-shadow:0 0 1px primary }`; title `0.75rem` w400 ls
  `.00625rem`. Matched (rhythm now 48px per item).
- **Idea card** (`.left-panel li`): `border:1px outline-variant`, radius 10px,
  padding 16px, **width 400px**; `:hover:not(.selected){bg:surface-container}`;
  `.selected{bg:blue-variant98;border:primary}`; `li+li{margin-top:8px}`.
  Loading state: 3 skeleton lines (50/90/80% width) + shimmer.
- **Recents card** (`.card`): radius 12px, padding 16px, gap 8px,
  `box-shadow:0 1px 2px rgba(0,0,0,.15),0 2px 10px rgba(0,0,0,.1)`;
  `.top-bar{gap:6px;margin-bottom:8px}`; winning chip `bg:green90`; winning
  list `12px w400 ls .00625rem`, `li+li{margin-top:16px}`. All matched.
- **fadeIn keyframe**: `0%{opacity:0;translate:0 16px} to{opacity:1}`,
  `0.3s ease-in-out forwards`, gated on `prefers-reduced-motion:no-preference`,
  on landing content + tournaments section. Added.
- **Landing metrics**: `.landing-content{max-width:760px;margin:24px auto 0}`,
  `.tournaments-section{width:350px}`.
- **Full light + dark MD3 ramps** (`--gm3-sys-color-*` fallback pairs): light
  and dark values captured in `reference-values.md`; the dark shell neutrals
  were retuned to match (`#1e1f20`/`#282a2c`/`#333537`/`#e3e3e3`/`#c4c7c5`/
  `#8e918f`/`#444746`).

## Not extracted / deferred

- **Decorative gradient blob** on the home hero — an inline animated SVG
  (`.overview-blocks .background`), too costly to lift exactly; left out
  rather than approximated.
- **Step-circle treatment** — reference uses a *light pastel* purple70 circle;
  we render a dark-filled teal one (green-not-purple is deliberate; the
  fill-vs-tint is the open judgment call).
- **`system-prompt.md`** (the agent's textproto `Config` spec) and the
  **network HAR** are engine/API references, not UI — noted, out of scope for
  the visual pass.

## Deliberate (leave as-is)

Teal/green accent for brand elements (logo, composer submit, stat value),
"Co-Scientist" wordmark, custom composer with source-button options, the
4-tab report structure, the Agent Insights panel + stat cards (approved
ESN-edition hybrid), the "Logs" control.
