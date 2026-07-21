# User audience modes — design

Date: 2026-07-17
Status: approved design, pre-implementation

## Goal

Tailor the workbench to three audiences without adding auth machinery:

1. **Google AI Co-Scientist team** — a personal message from Guy plus a
   dedicated page of recommendations for the official product.
2. **SBI/UCD researchers** — early testers of the product. Their runs and
   chat answers are grounded in background material about their lab and
   research; the home screen offers suggestions relevant to their work; the
   header offers an early-access pilot guide with a feedback channel.
3. **General users** — the app exactly as it is today. No changes.

The affiliation is self-declared (honor system): a centered popup on first
visit asks the user to pick, the choice persists in localStorage, and it can
be changed later from Settings. No access codes, no server-side verification.

## Non-goals

- No per-audience authentication or capability gating. The existing
  researcher access-code flow (`app/app/auth.py`) is untouched.
- No per-audience engine tool configuration. `TOOLS_CONFIG` (e.g.
  `indra_cancer.yaml`) stays a server-level env setting.
- No per-audience run tiers, limits, or feature flags.

## Audience model (frontend)

New file `app/frontend/src/workbench/audience_context.tsx`, mirroring the
existing `theme_context.tsx` pattern (plain React context + localStorage, no
state library):

- `export type Audience = 'general' | 'google' | 'sbi_ucd'`
- Storage key: `cosci-audience`. Unknown/absent stored values read as
  `null`, distinguishing "never chose" (show the popup) from an explicit
  General choice.
- `AudienceProvider` nests inside `ThemeProvider` in `workbench_app.tsx`.
- `useAudience()` returns `{audience: Audience | null, setAudience}`.
  Consumers that need a concrete value treat `null` as `'general'`.

## Affiliation dialog

New `audience_dialog.tsx` rendered by the workbench shell when the stored
audience is `null`: a centered modal (scrim + panel styled after the
existing `settings_dialog.tsx` classes) with three option cards:

- "Google AI Co-Scientist team"
- "SBI / UCD researcher"
- "General"

Picking one calls `setAudience` and closes the dialog. There is no dismiss
without choosing (Escape/scrim-click default to General) so the stored value
is always concrete after first interaction.

The Settings dialog gains an "Affiliation" row (new section or an entry in
an existing section) that reopens the same three-way choice, so the mode is
switchable at any time.

## Header control swap

`ShellHeader` (`layout_header.tsx`) currently always renders
`DiagnosticsControl` (the Logs button + popover). It becomes
audience-conditional; all variants reuse the existing `ShellPopover`
render-prop and the `activePanel`/`onTogglePanel` mutual-exclusion
machinery, so only the slot's content changes:

| Audience | Header control |
|---|---|
| `general` / `null` | `DiagnosticsControl` (unchanged Logs) |
| `google` | `GoogleTeamControl` — popover with the personal message and a link to the recommendations page |
| `sbi_ucd` | `PilotControl` — "Early access" popover: welcome note, what to try, known limitations, feedback mailto link |

## Google recommendations page

A new route `/recommendations` registered in `workbench_app.tsx`,
rendering a static page of product recommendations for the official
Co-Scientist. Linked from the `GoogleTeamControl` popover. The route is
reachable regardless of audience (honor system; nothing sensitive).

## SBI/UCD context injection (backend)

The only backend change, gated on `audience == 'sbi_ucd'`:

- `CreateRunRequest` and `AskRequest` (`app/app/runs_models.py`) gain an
  optional `audience: str | None` field, pattern-validated to
  `^(general|google|sbi_ucd)$`.
- New module `app/app/audience.py`: loads per-audience markdown from
  `app/app/content/` (cached after first read). `audience_context(audience)
  -> str` returns the file's text for `sbi_ucd` and `""` otherwise.
- **Run planning/generation:** during setup resolution in `runs_models.py` /
  `run_modes.py`, a non-empty audience context is stored in the durable
  `setup` block under a new `audience_context` key, and `setup_guidance()`
  renders it as an additional guidance section so the supervisor and
  generation agents receive it. It is not merged into the user-visible
  `requirements` list, keeping run-spec cards clean.
- **Chat Q&A:** `build_system_prompt` (`app/app/qa.py`) appends the context
  block when the ask request carries `audience='sbi_ucd'`.
- The audience is persisted in the run's `config_json` for provenance;
  switching modes later does not rewrite past runs.

Frontend plumbing: `createRun` and `askRunQuestion`
(`app/frontend/src/api/runs.ts`) accept an `audience` field, populated from
`useAudience()` at the call sites (`chat_session_start_run.ts` and the ask
handler). The field is always sent when an audience is stored (provenance);
it changes server behavior only for `sbi_ucd`.

## Home suggestions

`SUGGESTIONS` in `chat_home_stage.tsx` becomes audience-aware: `sbi_ucd`
gets three suggestion prompts tailored to SBI/UCD's research focus (same
`{preview, prompt}` shape); other audiences keep the current array.

## Content files (drafted, easily editable)

All audience-specific prose lives in dedicated files so revising content
never touches logic:

- `app/app/content/sbi_ucd_context.md` — lab background and research
  summary injected into prompts. Shipped as a clearly-marked first-pass
  draft assembled from public SBI/UCD information; Guy refines it later.
- `app/frontend/src/workbench/audience_content.ts` (or colocated constants)
  — the Google personal message, the recommendations page copy, the SBI/UCD
  pilot-guide copy and feedback address, and the SBI/UCD suggestion prompts.
  All shipped as drafts for Guy to edit.

## Testing

- **Audience context/dialog (Vitest + RTL):** localStorage persistence;
  popup shows when unset and not after a choice; settings switch updates
  the context.
- **Header swap (RTL):** each audience renders its control; popover
  open/close still works through the shared shell machinery.
- **Backend (pytest):** `audience_context()` returns content only for
  `sbi_ucd`; run creation with `audience='sbi_ucd'` persists the context in
  the setup block and `setup_guidance()` renders it; ask requests include
  the block in the system prompt for `sbi_ucd` and omit it otherwise;
  invalid audience values 422 at the edge.

## Error handling

- Missing/unreadable content file: `audience_context()` logs a warning and
  returns `""` — runs proceed ungrounded rather than failing.
- Corrupt localStorage value: read as `null`, popup shows again.
- Old runs without an `audience` key behave as `general` everywhere.
