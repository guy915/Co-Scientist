# Live-footage frames

Curated frames extracted 2026-09-03 from the two real-product screen
recordings that lived at `references/core/google-co-scientist/media/live-footage/`
(gitignored, never in git history, deleted by the owner separately from this
commit — see `docs/CORPUS-EXTRACTION.md` row `R13-1`). Both source mp4s were
watched in full, in order, before this set was chosen; this is the curated
evidence, not a raw dump. Full context and findings: `docs/CORPUS-EXTRACTION.md`
rows `R13-1`–`R13-3` and `R13-13`–`R13-15`, and `docs/CORPUS-STATUS.md`'s R13
region.

**Source files** (both H.264, 120 fps, gitignored by `.gitignore:46`):

- `mash-fibrosis-prompt-setup.mp4` — 30.0 s, 3602 frames, 3102×1424.
- `mash-fibrosis-research-plan-and-run.mp4` — 80.0 s, 9600 frames, 2490×1954.

**Extraction method.** `ffmpeg` sampled each source at a fixed rate — 2 fps
for `prompt-setup`, 1.5 fps for `research-plan-and-run` — and every sampled
frame was downscaled to 1600 px wide and reviewed in order (180 frames
total, tiled into labelled contact sheets for the first pass, then read
individually at full 1600 px resolution where evidence warranted a closer
look). The frames below are the subset that carries evidence; most are that
same 1600 px-wide extraction re-exported as JPEG, except
`setup-connectors-menu-native-crop-t17.5s.jpg`, which was cropped from a
**native-resolution** (3102×1424) single-frame extraction so the eighth
connector's label would actually be legible.

Filenames encode source (`setup`/`plan`) and timestamp; a timestamp is the
exact `(sampled-frame-index − 1) / sample-rate-fps`, not a rounded label.

## `setup-*` — from `mash-fibrosis-prompt-setup.mp4`

| Frame | Timestamp | Shows |
|---|---|---|
| `setup-agent-gallery-t00.0s.jpg` | 0.0 s | The Gemini Enterprise agent gallery. Co-Scientist is one card among Google's own agents (Deep Research, NotebookLM, Idea Generation) under "Made by Google", alongside a separate "From your organization" row of custom agents. |
| `setup-coscientist-landing-t04.5s.jpg` | 4.5 s | The Co-Scientist landing page after opening its card: "Drive novel scientific discovery with Co-Scientist," a numbered 3-step flow (**1** Create a Research goal, **2** Generate hypotheses, **3** Evaluate and rank), three example-prompt chips, and an empty "Recents" panel ("You have not started any sessions yet"). |
| `setup-composer-goal-text-t11.5s.jpg` | 11.5 s | The composer accepting free-form text typed directly by the user in a `Title: …` / `Research challenge: …` shape — not separate structured fields. This is the literal text later reflected in the research-plan card. |
| `setup-connectors-menu-t17.5s.jpg` | 17.5 s | The composer's connectors menu open (full 1600 px frame, for on-screen context): an "Enable all connectors" toggle above eight per-source rows. |
| `setup-connectors-menu-native-crop-t17.5s.jpg` | 17.5 s | The same menu, native-resolution crop for legibility. Reads, top to bottom: **Google Search**, **Pubmed**, **ArXiv**, **BioRxiv** (all four toggled on, blue) — then **Calendar** ("Authorize", off), **Chat** (off), **Drive** (off, with a disconnected-link glyph), and an eighth row labelled **"Geat"** (off) with a four-colour grid icon. "Geat" is transcribed verbatim; what product it names is not established by this footage — it does not match any Google Workspace product name and may be a demo-build labelling artifact. |
| `setup-session-thinking-t29.5s.jpg` | 29.5 s | The last frame of this clip: after submission, the typed goal collapses into a chat bubble (with a chevron to re-expand) and a "Co-Scientist / Thinking…" status appears; the composer is replaced by a plain "Type to edit session details" box. |

## `plan-*` — from `mash-fibrosis-research-plan-and-run.mp4`

| Frame | Timestamp | Shows |
|---|---|---|
| `plan-card-requirements-t07.3s.jpg` | 7.3 s | The research-plan chat card mid-stream: title, `Goal:`, and the six `Requirements:` bullets, in the card/chat rendering (distinct from the later report-page rendering of the same content — see `plan-report-criteria-prose-t65.3s.jpg`). |
| `plan-card-attributes-criteria-t09.3s.jpg` | 9.3 s | The plan card's `Attributes:` (five axes: Mechanism Novelty, Human Relevance, Clinical Translatability, Target Area, Validation Plan Strength) and the start of `Criteria:`, fully rendered. **Word-for-word match** to the transcription in `docs/CORPUS-EXTRACTION.md` (~line 1930) that `run_modes/attributes.py`/`run_modes/criteria.py` cite. |
| `plan-card-focus-tier-start-t31.3s.jpg` | 31.3 s | The plan card's `Focus` (Prefer evidence / **Balance** selected / Prefer novelty / Breakthrough) and `Tier` (Express / **Standard** selected / Extended / Ultra) sections, fully rendered with the Cancel / Start research buttons. Confirms the published tier and focus option sets and order exactly, and that **Standard** (not Extended or Ultra) is selected at this point. |
| `plan-readonly-thinking-t47.3s.jpg` | 47.3 s | Immediately after "Start research" is clicked: the plan scrolls out of view, "Co-Scientist / Thinking…" appears, and the composer is replaced by "This conversation is read only." — the whole chat locks; there is no way to keep typing into this session once a run starts. |
| `plan-readonly-tier-extended-t54.0s.jpg` | 54.0 s | The user scrolls back up through the now-read-only plan card while "Thinking…" continues below. Here **Extended** (not Standard) shows as the selected Tier radio — see `R13-14`: a genuine footage discrepancy between this frame and `plan-card-focus-tier-start-t31.3s.jpg`, not resolved by anything visible in either video. |
| `plan-session-started-card-t56.0s.jpg` | 56.0 s | "Your session has been started and your team of AI agents has started research!" message, a session card ("Epigenetic and stromal reversal strategies for MASH-associated liver fibro… [Open]"), and two follow-on actions: "View session details" / "Start a new research goal session on a new topic." |
| `plan-report-four-tabs-t66.0s.jpg` | 66.0 s | **The exact frame `docs/UI-FIDELITY.md` cites** for the four-tab report mapping. Opening the session shows a report page with tab bar **Goal Details · Learning · Research Overview · All Ideas** (book / open-book / clipboard / lightbulb icons), Goal Details active with a **blue** underline, and the Goal/Requirements/Attributes content rendered as prose. |
| `plan-report-criteria-prose-t65.3s.jpg` | 65.3 s | The same Goal Details page scrolled further down: `Criteria:` renders here as one condensed prose sentence — *"Criteria: should be correct, should be novel, should maximize impact."* — a different shape from the plan card's `Idea correctness: Required` / `Idea novelty: Required` / `Maximize impact: Yes` bullets (`plan-card-attributes-criteria-t09.3s.jpg`). Whether Focus/Tier are also restated further down this page is not established — the visible scrollbar suggests more content below than either video frame captured. |
| `plan-recents-progress-card-t76.0s.jpg` | 76.0 s | The last useful content in this clip: back on the agent home page, the "Recents" panel now shows an in-progress card for this run — "Time elapsed: –", a spinner, "In Progress : 0%", and a status line "Exploring focus areas". The 80 s clip ends before the run advances past 0%; no hypothesis, tournament, or Learning/Research Overview/All Ideas *content* is ever shown in either video. |
