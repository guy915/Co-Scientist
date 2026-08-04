# UI Fidelity Audit — replica vs. reference

This audits the **visual/UX fidelity** of `app/frontend` (the workbench) against
the real Google product it replicates. It is separate from
[`FIDELITY.md`](FIDELITY.md), which covers *behavioural/engine* fidelity.

**Scope of this pass:** reconnaissance + audit only. No `app/frontend` source was
modified. Every claim below is grounded in a cited file, video frame, or CSS
selector, and labelled with a confidence/verdict. This file **supersedes** the
earlier partial draft (see "Corrections vs. the prior draft" near the end).

---

## 1. The two-product reference model (read this first)

The repo carries **two** distinct real references plus several secondary skins.
They play different roles and must not be conflated — the prior audit's failure
came from auditing against one and inferring "invented" from its absence.

**A. `references/core/google-co-scientist/` — the FUNCTIONAL SOURCE OF TRUTH.**
This is the real AI Co-Scientist. It carries written specs
(`product-surface-and-ux.md` et al.) *and*, most importantly,
`media/live-footage/*.mp4` — the real UI in motion. When a spec still and a
live-footage frame disagree, **the live footage wins** (it is the newest, and it
is the running product, not a description of it).

> **Two eras inside the core reference.** The core media set contains **two
> different report UIs**:
> - **Older (ESN / SARS-CoV-2 stills)** — `esn-*.jpg`: tab bar
>   *Ideas · Knowledge Base · Summary · Run Specification*, **green** active
>   underline, an "Agent Insights" panel, and a 4-up stat-card row. The written
>   spec (`product-surface-and-ux.md` §"Stage 5 — The Goal Report", lines 66–79)
>   describes this same older set.
> - **Newer (MASH-fibrosis live footage)** — `mash-fibrosis-*.mp4`: tab bar
>   *Goal Details · Learning · Research Overview · All Ideas*, **blue** active
>   underline.
>
> **Our app mirrors the newer (live-footage) era** and aliases the older tab
> names onto it. Several "gaps" below are only gaps *if the older ESN era is in
> scope* — hence they are filed as **decisions**, not drift. Confirming the
> canonical era (Question Q1) collapses most of them.

**B. `references/ui-ux/idea-generator/` — the PIXEL-TRUTH TWIN.** Gemini
Enterprise "Idea Generation" is Co-Scientist's business twin on the same base
UI. It is the richest *pixel* source (downloaded HTML + real CSS in `*_files/`
dirs, light+dark screenshots), so it is authoritative for **exact colours,
spacing, fonts, radii**. But it diverged for a different product: it renames
"hypothesis" → "idea" and uses Google's blue `#0b57d0` primary. Use it for
pixels, not for lexicon or product structure.

**C. Secondary skins** — `references/ui-ux/gemini-enterprise/` (shared base
shell; HTML/CSS), `references/ui-ux/gemini/` (plain consumer Gemini — mostly
unrelated, do not anchor on it), `references/ui-ux/notebooklm/` (UI lineage
only), `references/ui-ux/legacy-workbench-ui/` (**our own** pre-refactor UI — not
a source of truth).

### Owner's deliberate divergences (CORRECT — never flagged as drift)

These are intentional single-agent adaptations by the product owner. Where seen,
they are labelled INTENTIONAL and left alone:

| Divergence | Status |
|---|---|
| **Green accent** (teal `#1a6b6b` light / mint `#7fd7bf` dark) replacing Google's blue primary | Intentional — owner's own brand. Do **not** propose reverting. |
| **"Co-Scientist"** navbar instead of "Gemini Enterprise" | Intentional (single-agent). Footage still reads "Gemini Enterprise"; that is the *reference*, ours is the deliberate rename. |
| Owner-added **"Logs"** button | Intentional. |
| **Trimmed settings / surfaces** | Intentional. |
| **Copy / text changes** | Intentional (explicitly named category). |

A few further unnamed deliberate changes exist. **Rule applied throughout:** when
unsure whether a divergence is intentional, it is raised as a QUESTION, never
asserted as drift.

---

## 2. Tab / surface mapping (ours ↔ reference)

Our live report lives in `run_detail.tsx`, routed by the canonical tab table in
the sibling `run_tabs.ts` (`TABS`, line 7). It mirrors the **newer**
live-footage era, and `run_tabs.ts`'s `TAB_ALIASES` (line 14) absorbs the
**older** spec/ESN names so old deep-links still resolve.

| Our tab (`TAB_META`) | Newer footage (canonical) | Older ESN / spec (aliased) | Verdict |
|---|---|---|---|
| `details` → **Goal Details** | Goal Details | Run Specification(s) → `specifications`/`specs` | Faithful (F1) |
| `learning` → **Learning** | Learning | Knowledge Base → `knowledge`/`evidence` | Faithful (F11) |
| `overview` → **Research Overview** | Research Overview | Summary → `summary`/`report` | Faithful structure; content lighter (F9) |
| `ideas` → **All Ideas** | All Ideas | Ideas → `hypotheses` | Faithful (F1); ESN enrichments absent (F3) |

**Evidence for the mapping:** newer era —
`media/live-footage/mash-fibrosis-research-plan-and-run.mp4` frame ≈66 s (re-
extracted, downscaled to width 900) shows exactly these 4 tabs, icon+label, with
"Goal Details" active. Older era — `media/hypothesis-generation/esn-*.jpg` +
`product-surface-and-ux.md` §Stage 5.

---

## 3. Verified findings (grouped by severity)

Severity legend: **WIN** (faithful) · **DECISION** (owner tie-break needed;
often era-conditional) · **INTENTIONAL** (a deliberate owner divergence,
confirmed) · **POLISH** (small cosmetic delta) · **DRIFT** (unambiguous
divergence from the canonical reference). Confidence is stated per item.

### WINS (faithful — do not touch)

**W1 — Report tab bar labels + order (F1).** *Confidence: high.*
- **Reference truth:** `mash-fibrosis-research-plan-and-run.mp4` ≈66 s — 4 tabs,
  icon+label, L→R: *Goal Details* (active, underlined) / *Learning* /
  *Research Overview* / *All Ideas*.
- **Our impl:** `run_tabs.ts:7` `TABS=['details','learning','overview','ideas']`;
  `run_detail_shell.tsx`'s `TAB_META` maps to the four labels above.
- **Verifier note:** independently re-extracted the frame and read the code —
  labels and order are 1:1. Not drift.

**W2 — Active-tab underline colour is BLUE, and so is ours (reverses the prior
draft).** *Confidence: high.*
- **Reference truth:** in the **newer** era the active tab ("Goal Details")
  underline is **blue**, not green — confirmed in the 66 s frame (dark mode,
  clearly a blue accent bar under the active tab). The **green** underline
  appears only in the **older** ESN stills (`esn-knowledge-base-clinical-
  definitions.jpg`).
- **Our impl:** `run_detail.tsx:78–79` `REPORT_TAB_SELECTED_CLASSES` uses
  `text-cosci-blue` + `after:bg-cosci-blue-strong`; `--cosci-blue-strong` =
  `#1a73e8` light / `#8ab4f8` dark (`reference_surface.css:17,38`). Ours is blue.
- **Verifier note:** the prior draft filed this as **Drift ("should be green")**.
  That was an *era* artifact — it compared our newer-era UI to an older-era still.
  Against the canonical newer footage, the blue underline is **faithful**. See
  "Corrections vs. the prior draft".

**W3 — Learning (Knowledge Base) tab structure (F11).** *Confidence: high.*
- **Reference truth:** `esn-knowledge-base-analytical-pipelines.jpg` — serif
  section heading, bold **Summary**, body prose, **Show more** chevron, then a
  **References** section with a **Search references** magnifier input and numbered
  `[N]` rows each ending in an outlined **Open** button (external-link icon).
- **Our impl:** `run_detail_learning.tsx` — Summary + Show more/less toggle
  (`:78–102`, `expand_more`/`expand_less` chevrons); `ReferencesBlock` (`:132–196`)
  = "References" heading + "Search references" input (`search` icon, `:144–157`) +
  `[index+1]` rows (`:163`) + "Open" `<a>` with `open_in_new` icon (`:169–182`).
- **Verifier note:** structural inventory is a 1:1 match. Two out-of-scope
  cosmetic deltas noted for the record (see P1, P2 below): reference headings are
  serif, ours render in the global sans; reference "Open" is an outlined pill,
  ours is a bare text link.

**W4 — Green accent applied consistently (F10 conclusion).** *Confidence: high.*
- **Owner-intentional truth:** the green accent replacing Google's primary is the
  known deliberate owner divergence.
- **Our impl:** `reference_surface.css:5` `--cosci-teal:#1a6b6b` (light) / `:8,:40`
  `--cosci-green:#7fd7bf` (dark); `:26,:28` step-dot + logo = teal (light);
  `:48,:50` = green (dark); `home_surface.css:81–91` `.reference-step-number`
  consumes `--cosci-step-dot-bg`; `lib/theme.ts:7` MD3 seed `#1A6B6B`. Applied
  cleanly across light and dark.
- **Verifier note — factual correction folded in:** the finding's *rationale*
  originally said the footage accent is "purple". **That is wrong.** The
  reference primary is **blue**: spec `product-surface-and-ux.md` ≈line 181
  `--color-primary:#0b57d0`; the idea-generator's applied CSS uses `#0b57d0`; the
  dark-footage accent is the M3 blue `#a8c7fa` family (our own token
  `--cosci-blue:#a8c7fa`, `reference_surface.css:37`). (Purple hexes exist in the
  idea-generator bundle only as the dormant MDC/Angular-Material library default
  theme, never as the rendered brand accent.) The **conclusion is unchanged**:
  green is an intentional, faithful, consistent divergence — the reference it
  replaces is blue, not purple.

### INTENTIONAL DIVERGENCES (confirmed deliberate — labelled, not fixed)

**I1 — Ideas detail nomenclature: "Hypothesis overview" vs. twin's "Idea
overview" (F6).** *Confidence: high on facts; verdict INTENTIONAL with a caveat
question.*
- **Reference truth (pixel twin):** `idea-generator/ideas-results/ideas-results.html`
  — detail pane opens with **"Idea overview"** (line ≈11715); Sections rail lists
  *Idea overview / Description / Review summary / Full review / Tournament
  performance* (grep: 2× "Idea overview", 0× "Hypothesis overview").
- **Our impl:** `ideas_tab.tsx:234` `DetailSection title="Hypothesis overview"`;
  `:306–312` SectionsRail = *Hypothesis overview / Description / Review summary /
  Full review / Tournament performance*; `:230` breadcrumb "AI Co-Scientist >
  Ranked hypothesis > {title}"; `:135` aria-label "Ranked hypothesis list".
- **Verifier note:** the sole delta is one word (**Hypothesis** vs. **Idea**) —
  the other three named labels match exactly. The twin renamed hypothesis→idea
  for its product; the **functional** Co-Scientist uses "hypothesis" pervasively
  (core spec: "ranked hypotheses", "top-ranked hypotheses"; neither exact string
  "Idea overview"/"Hypothesis overview" appears in the core spec). Our surface is
  internally consistent with the hypothesis lexicon while the *tab* is still
  user-labelled "Ideas"/"All Ideas". This aligns our copy with the real product's
  language and fits the owner's "copy/text changes" allowance → **INTENTIONAL.**
  ⚠️ *Flips to a 1-word POLISH fix at `ideas_tab.tsx:234,307` only if the owner
  wants strict pixel-parity with the twin rather than lexical parity with
  Co-Scientist* (Question Q5).

**I2 — Home 3-step explainer copy (F8).** *Confidence: high on facts; verdict
INTENTIONAL.*
- **Reference truth:** real Co-Scientist steps (footage `mash-fibrosis-prompt-
  setup.mp4`, home): *1 Create a Research goal / 2 Generate hypotheses / 3
  Evaluate and rank*. Twin steps (`idea-generator/home-page/home-page.html`): *1
  Getting started / 2 Idea generation / 3 Evaluation and ranking*.
- **Our impl:** `chat_home_stage.tsx` `SESSION_STEPS` = *Frame the research goal /
  Generate hypotheses / Pressure-test the best ideas*.
- **Verifier note:** our copy diverges from **both** references, but note the
  tell: our step-2 label "Generate hypotheses" is a **verbatim** match to the
  real product's step 2 (not the twin's "Idea generation"), while steps 1 & 3 are
  reworded. Keeping the real product's wording verbatim while custom-rewording 1
  and 3 is a deliberate, source-aware edit — squarely the owner's "copy changes"
  category → **INTENTIONAL.** (Confirm intent: Question Q4.)

### DECISIONS (owner tie-break needed — mostly era-conditional)

**D1 — Which report era is canonical (F2).** *Confidence: high on facts;
severity DECISION.*
- **Reference truth:** two real eras exist (see §1). Ours mirrors the newer
  (footage) era and aliases the older (ESN/spec) names.
- **Our impl:** `run_detail.tsx:37,47–52` (newer labels) + `:99–107` `TAB_ALIASES`
  (older names → live tabs).
- **Verifier note:** this is the **root** decision. If the newer era is canonical
  (very likely — it is the running product in the newest footage), then D2/D3
  below are **out of scope**, not drift. Only a human can set the target →
  **Question Q1.** Our code already responsibly encodes the newer era and absorbs
  the older names, so **no code change is warranted regardless of the answer.**

**D2 — Ideas tab "Agent Insights" panel + 4-up stat cards (F3).** *Confidence:
high on facts; severity DECISION (era-conditional on D1).*
- **Reference truth (older ESN only):** `esn-ideas-agent-insights.jpg` — a
  collapsible **Agent Insights** panel (sparkle icon + synthesized paragraph)
  above a 4-up stat row: *High potential ideas* (4) / *Non-viable ideas* (20) /
  *Number of verified ideas* (15) / *Sources analyzed* (444), each with an (i)
  icon and a large green value.
- **Our impl:** no counterpart. `ideas_tab.tsx` renders only the 3-column
  rank/detail/sections layout; repo-wide grep for `agent insight|high potential|
  non.viable|verified ideas|sources analyzed|stat.?card` returns **0** hits on the
  Ideas surface (the only `statCards` hit is in `overview_tab.tsx`, an unrelated
  and unwired surface).
- **Verifier note:** present-in-ESN, absent-in-ours. A real content gap **iff the
  ESN era is in scope**; otherwise out of scope. Gated by Q1. → **Question Q1.**
- **Resolution (owner decision):** the panel + stat cards were built for a time
  and then **removed as out of scope** — the derived metrics (Elo-bucket
  "high potential/non-viable", verified-citation counts) were an interpretation
  the ESN reference doesn't actually specify. `ideas_tab.tsx` again renders only
  the 3-column rank/detail/sections layout. Do not re-add as a fidelity gap
  without an explicit scope decision.

**D3 — Research Overview summary richness (F9).** *Confidence: high on facts;
severity DECISION.*
- **Reference truth (idea-generator overview):** `ideas-results/results-overview.jpg`
  leads the Overview with a combined stat sentence — *"A total of 133 ideas were
  explored over 3 hours with the highest Elo rating [inline link] of 1735 points
  and a total of 1360 matches were played"* — followed by a **"Winning ideas"**
  bulleted list, then Session details (Goal / Requirements).
- **Our impl:** `run_detail.tsx:439–446` renders "Tournament summary" as the plain
  one-liner `${matches.length} tournament matches have been recorded for this
  run.` plus a Top-ideas Elo list (`:403–437`). Whole-file grep finds **0** of
  "were explored" / "matches were played" / "highest Elo" / "Winning ideas".
- **Verifier note:** genuinely plainer than the reference; **not** on the
  deliberate-divergence list. The data to build it is already in the payload
  (`run_types.ts:177` leaderboard `{id,title,elo}`, plus hypothesis and match
  counts; only "duration" would need deriving from run timestamps), so the
  enrichment is feasible. May be intentionally simplified for the newer-era
  report. → **Question Q7.** *(Honesty caveat: the captured `ideas-results.html`
  I grepped was in a "Session details only" state and lacked the stat phrases;
  this confirmation rests on the `results-overview.jpg` screenshot, which is
  authoritative primary visual evidence.)*

**D4 — Composer connectors: 1 vs. 4 + master toggle (F4).** *Confidence: high on
facts; severity DECISION (very likely intentional trim).*
- **Reference truth:** `mash-fibrosis-prompt-setup.mp4` ≈20 s — connectors
  dropdown with an **"Enable all connectors"** master toggle, then **Google
  Search** (on) / **Pubmed** (on) / **ArXiv** (on) / **BioRxiv** (on), plus
  Calendar ("Authorize") / Chat / Drive / Gmail (off), each with a coloured
  source icon. Spec corroborates multi-source retrieval
  (`product-surface-and-ux.md` ≈220,229: Web search, PubMed, arXiv, ChEMBL,
  UniProt).
- **Our impl:** `chat_composer.tsx:35` `COMPOSER_CONNECTORS = ['PubMed']`; menu
  (`:346–380`) renders exactly one row (`article` icon + on/off switch), **no**
  master toggle, no other sources.
- **Verifier note:** the delta (4 scientific connectors + master vs. 1 PubMed,
  no master) is real and large. Most likely an intentional single-agent trim
  (owner's "trimmed settings"), but the connectors trim is not *explicitly*
  enumerated, so confirm rather than assume. → **Question Q2.**

**D5 — Orphaned tab components + stale `CLAUDE.md` (F5).** *Confidence: high;
internal hygiene; severity DECISION.*
- **Reference truth:** N/A (internal).
- **Our impl:** `run_detail.tsx:24` imports **only** `IdeasTab`. The other three
  live tabs render from **inline/local** views: `GoalDetailsView` (local,
  `run_detail.tsx:322`), `LearningView` (`run_detail_learning.tsx`),
  `ResearchOverviewView` (local, `run_detail.tsx:342`). Five tab files are
  orphaned (0 non-test importers): `chat_tab.tsx`, `evidence_tab.tsx`,
  `overview_tab.tsx`, `run_specifications_tab.tsx`, `tournament_tab.tsx` — each
  with a colocated `*.test.tsx` (the only remaining references). `ideas_tab` is
  the sole wired one.
- **Verifier note — correction to the finding's own wording:** the claim said
  "five of the six report tab components… lists report_tab among them", but
  **`report_tab.tsx` does not exist on disk** (verified: `find … -name
  'report_tab*'` → none). Actual inventory: **6 real non-test `.tsx` files, 5
  orphaned, 1 (`ideas_tab`) wired.** `CLAUDE.md` (line ≈154) is stale in **two**
  ways: it lists the orphaned tabs as the live set, **and** it names a
  `report_tab.tsx` that no longer exists. Action: retire the 5 dead files (+
  tests) or wire them, and fix `CLAUDE.md` either way. → **Question Q3.**

**D6 — Public / landing routing vs. `CLAUDE.md` (F12).** *Confidence: high;
doc-vs-code mismatch; severity DECISION.*
- **Reference truth:** N/A for pixel fidelity (the real product is one agent
  inside the Gemini Enterprise shell).
- **Our impl:** `workbench_app.tsx:25–56` — `/`→`ChatWorkspace`; `/runs` and
  `/runs/new`→`<Navigate to="/" replace/>`; `/runs/:id` and `/runs/:id/:tab`→
  `RunDetail`; `*`→`NotFoundPage`. **No** `/about`, **no** `/demos/:slug` (repo
  grep for those paths → none). `src/public/` retains only
  `no_index`/`not_found_page`/`public_link_button`/`seo`; `landing_page.tsx`,
  `demo_page.tsx`, `demo_manifest.ts` are **absent**; there is no standalone
  `dashboard.tsx`.
- **Verifier note:** `CLAUDE.md` (Routing, lines ≈150,152) still documents
  `/about`, `/demos/:slug`, and a `/runs` dashboard as live, and names the absent
  `public/` files. Every factual claim checks out; the doc is stale. Fits the
  owner's "trimmed surfaces" pattern → treat as INTENTIONAL removal and reconcile
  the doc, pending a one-line confirm. → **Question Q8.**

### POLISH (small cosmetic deltas — record for the final pass)

**P1 — Learning section headings: serif in reference, sans in ours.**
*Confidence: high; low impact.*
- **Reference:** ESN Knowledge Base headings render in a **serif** face.
- **Our impl:** the report uses "Google Sans" sans-serif globally
  (`index.css:211–213`); `REPORT_H3_CLASSES` sets no serif family.
- **Verifier note:** out of scope for the F11 *structure* win, but a genuine
  typography delta. Confirm whether the owner wants the serif section headings.

**P2 — Learning "Open" affordance: outlined pill vs. bare link.** *Confidence:
high; low impact.*
- **Reference:** ESN "Open" is an **outlined/bordered pill** button (external-link
  icon).
- **Our impl:** a bare blue-text link (`REFERENCE_LIST_LINK_CLASSES` has no
  border), with the `open_in_new` icon present.
- **Verifier note:** small chrome nuance; bundle with P1 if the owner wants
  Learning-tab pixel parity.

*(No item currently rises to unambiguous **DRIFT**. The prior draft's one drift
claim — the green tab underline — was reclassified to W2 after era-checking the
canonical footage.)*

---

## 4. Open questions for the product owner

These block implementation of the DECISION items. Q1 is the keystone — answering
it resolves D2 and D3's scope.

- **Q1 — Canonical report era?** The reference has two real report UIs: older
  ESN (*Ideas · Knowledge Base · Summary · Run Specification* + Agent Insights
  panel + 4-up stat cards) and newer MASH footage (*Goal Details · Learning ·
  Research Overview · All Ideas*). We mirror the newer one. Is the newer footage
  era the canonical target (so the ESN stat-cards / Agent-Insights are **out of
  scope**), or should we backport the ESN-era Ideas enrichments?
- **Q2 — Composer connectors.** Real Co-Scientist shows Google Search / Pubmed /
  ArXiv / BioRxiv (all on) + an "Enable all connectors" master toggle
  (Calendar/Chat/Drive/Gmail off). Ours exposes only PubMed. Intentional
  single-agent trim, or surface the full multi-source menu + master toggle?
- **Q3 — Orphaned tab components.** `overview_tab`, `evidence_tab`,
  `tournament_tab`, `run_specifications_tab`, `chat_tab` are dead code (0
  importers); only `IdeasTab` is wired and `RunDetail` renders the other tabs
  inline. Delete them (and fix `CLAUDE.md`, which also references a nonexistent
  `report_tab.tsx`), or re-wire them?
- **Q4 — Home 3-step copy.** Real variants: *Create a Research goal / Generate
  hypotheses / Evaluate and rank* (footage) and *Getting started / Idea
  generation / Evaluation and ranking* (twin). Ours: *Frame the research goal /
  Generate hypotheses / Pressure-test the best ideas*. Confirm this reworded copy
  is the intended owner divergence.
- **Q5 — Ideas detail nomenclature.** Reference labels the first detail section &
  breadcrumb "Idea overview"; ours says "Hypothesis overview" / "Ranked
  hypothesis". Keep the hypothesis lexicon (arguably truer to the real
  single-agent Co-Scientist), or match the twin's "Idea overview" for pixel
  parity?
- **Q6 — Selected idea-row highlight.** Ours uses a soft custom blue
  (`--cosci-idea-row-selected-bg` `#f1f8fc` light / `#004b72` dark, border
  `#8ab4f8`/`#4aa5d8`; `reference_surface.css:75–77,146–148`). *Note:* a prior
  finding claimed the reference uses GM3 secondary-container `#c2e7ff` — that was
  **rejected as fabricated** (see §5). So this is a free design choice, **not** a
  drift; confirm the current softening is what you want, or name a target.
- **Q7 — Research Overview richness.** Reference overview leads with a combined
  "*N ideas explored over X hours, highest Elo Y, Z matches played*" stat sentence
  + a "Winning ideas" list. Ours is a plain one-liner. Add the combined stat
  sentence (data is available in the payload), or is the simpler summary intended
  for the newer-era report?
- **Q8 — Public/landing routing.** `CLAUDE.md` documents `/about`, `/demos/:slug`,
  and a `/runs` dashboard, but the shipped app redirects `/runs` and `/runs/new`
  to `/` and has no `/about` or `/demos` routes. Deliberately removed (update the
  doc) or temporarily disabled?
- **Q9 — Learning-tab typography (P1/P2).** Reference Knowledge Base uses **serif**
  section headings and an **outlined "Open" pill**; ours uses the global sans and
  a bare text link. Match the serif + pill, or keep the current chrome?

---

## 5. Corrections vs. the prior draft (what skeptics rejected/changed)

The earlier `ui-fidelity.md` (lettered findings A–H) and the raw candidate
findings were re-verified against primary evidence. Net changes:

- **Prior "Finding B" — active tab underline "should be green" (Drift) →
  REVERSED to WIN (W2).** The green underline is **older-ESN-only**; the
  canonical newer footage (66 s frame) shows a **blue** underline, which matches
  ours (`--cosci-blue-strong`). It was an era mismatch, not drift.
- **Prior "Finding D" / F5 wording — "`report_tab.tsx` is one of the six report
  tabs" → CORRECTED.** `report_tab.tsx` **does not exist**. There are 6 real
  non-test tab files; 5 orphaned, 1 (`ideas_tab`) wired. `CLAUDE.md` is stale in
  two ways (lists orphans as live *and* names the nonexistent `report_tab`).
- **F10 rationale — "footage accent is purple" → CORRECTED to blue.** The
  reference primary is blue (`#0b57d0` light / `#a8c7fa` dark). Purple appears
  only as a dormant library-default theme in the idea-generator bundle, never as
  the rendered accent. The **conclusion is unchanged**: the green accent is an
  intentional, faithful, consistent owner divergence.
- **F6 & F8 — proposed as copy "drift" → RECLASSIFIED to INTENTIONAL.** Both fall
  under the owner's explicitly sanctioned "copy/text changes"; F8's step-2 is a
  verbatim match to the real product and F6 aligns with the real product's
  hypothesis lexicon. Raised as questions (Q4, Q5), not asserted as defects.
- **F7 — "reference highlights the selected idea row with GM3
  secondary-container blue `#c2e7ff`" → REJECTED (fabricated reference truth).**
  In `idea-generator/ideas-results.html`, `#c2e7ff` occurs on the Material GM3
  **CircularProgress spinner track** and a `gb_`-prefixed Google-bar chrome
  element — **never** on a selected/active ranked-idea row. The claimed dark
  `#004a77` appears **0** times in the dark capture. There is no reference basis
  for recolouring our selected row; the "fix" would have painted it a spinner-ring
  colour. *(Aside: our tokens **are** named `--cosci-idea-row-selected-*`, lines
  75–77 / 146–148 — both the original finding and the rejection's parenthetical
  quibble about the name were imprecise; the load-bearing reason for rejection is
  the fabricated reference truth, which stands.)* Folded into Q6.
- **Prior draft's broader "invented/missing" framing — SUPERSEDED.** The prior
  draft already walked back the very first "everything is invented" audit; this
  pass keeps that correction and tightens the remaining items to
  evidence-grounded, era-aware DECISION/WIN/INTENTIONAL classifications with
  explicit confidence.

---

## 6. Method note

- **Reference roles were respected, not flattened.** Functional truth (core, incl.
  **live footage** as the newest running UI) vs. pixel truth (idea-generator twin)
  vs. our-own legacy UI (not truth). Where a spec still and live footage
  disagreed, footage won (the era question, W2).
- **Every claim is cited** to a file+line, a video frame at a timestamp, or a CSS
  selector, and labelled with confidence. Negatives ("absent in ours") were
  established by repo-wide grep across `app/frontend/src`, not by partial reads —
  the specific failure mode of the first audit.
- **Owner-intentional divergences were treated as correct** (green accent, navbar
  rename, Logs, trimmed settings/surfaces, copy). When intent was uncertain, the
  item became a QUESTION, never a drift assertion — per the hard lesson that a
  prior audit asserted confident negatives from a partial view and was wrong.
- **Image discipline:** all screenshots/frames were downscaled before reading
  (stills via `sips -Z 1000`; the one decisive video frame extracted pre-scaled
  with `ffmpeg -vf scale=900:-1`). Exactly one new video frame was read this pass
  (the 66 s underline-colour check that reversed prior Finding B); all other
  visual evidence was carried from the verified finding package's grounded reads.
- **Advisor** was unavailable this session (tool errored); findings rest on the
  independently re-verified evidence above.
