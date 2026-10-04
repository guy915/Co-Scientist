# Improvements

## Phase 1 — Reliability

The source is a production Express run, `04b988c6-d0c5-42be-9882-c993420d2be5`
("Glioblastoma BBB Drug Repurposing").

1. **Run failed outright.** Recorded error: `Task engine.fanout.reflection.item
   failed permanently: The provider may have accepted the request; acceptance
   and any charge are unconfirmed. Automatic replay was stopped.` One
   ambiguous-acceptance failure on a single reflection fanout item killed the
   whole run. Expected: drop that one item (the hypothesis stays unreviewed
   and is marked so), or retry it within the spend and retry budgets. The run
   must continue. Keep the "never blindly replay a possibly-charged call"
   invariant; change only the blast radius.
2. **Warning: `Schema validation failed on attempt 1: {'hypotheses': [...]} is
   not of type 'array'`** (`co_scientist.llm.attempts.json_attempt`, during
   generate). The model wrapped the array in an object. Unwrap a single-key
   object whose value is the expected array before validating, instead of
   spending a retry. See memory note "envelope-shape defect class".
3. **Warning: `Schema validation failed on attempt 1: [] should be
   non-empty`.** Identify the call (likely reflection or ranking) and fix its
   prompt or schema so an empty list is either valid or never requested.
4. **Warning: `app.claims: 1 cited span(s) could not be located in their cited
   source among 12 shown passage(s); verdict unproven`.** This is the evidence
   gate working as designed. Lower it to INFO; keep the verdict.

## Phase 2 — Workbench UI

5. **Remove the supervisor allocation ledger** (the collapsible "Supervisor
   allocation ledger · N decisions" block on the run results page). Starting
   points: `app/frontend/src/workbench/pages/run_detail*.tsx`,
   `app/app/runs/collections.py`, `app/frontend/src/api/runs.ts`. Remove the
   endpoint only if nothing else consumes it.
6. **Remove empirical outcomes** (decided). Covers `app/app/store/outcomes.py`,
   the `hypothesis_outcomes` and `outcome_refinement_actions` tables
   (`app/app/store/schema.py`), the routes in `app/app/runs/contrib.py` and
   `collections.py`, the outcome refinement package (commit `019c10c0`), the
   frontend files `workbench/components/tabs/hypothesis_outcomes.tsx`,
   `hypothesis_outcome_refinement*` and `ideas_detail_pane.tsx` usage, plus
   related tests, e2e specs and docs. It was added in `75b99dac` (2026-09-23).
   Any durable task type it registered needs a safe path for queued rows.
7. **Run type cards:** when no API key is set, Standard, Extended and Ultra
   currently say "Requires your own API key (Settings > Model)." as their
   description. Instead, render them greyed out and disabled, keeping their
   real description. A tooltip or small hint may say a key is needed.
   Source: `app/frontend/src/workbench/run_spec.ts:161`.
8. **Activity log group titles:** drop the "· N steps" suffix
   (`run_detail_activity_log.tsx:168`). The screenshot showed "Reviewing
   hypotheses · 3 steps" with three identical "Reviewing hypotheses" sub-rows,
   which says nothing useful.
9. **Remove the Title field from the plan card** (decided).
   `chat_timeline_run_spec_editor.tsx` (form field), `chat_timeline_run_spec_card.tsx:52`
   (`SpecRow label="Title"`) and the `title` plumbing in `workbench/run_spec.ts`.
   The interview-derived title and the backend's `_populate_run_title`
   (`app/app/runs/crud.py:584`) stay, so runs still get titled.
10. **Edit prompt and Retry response disappeared.** Cause:
    `chat_workspace_timeline.tsx:74`, `revisable = !isAwaitingAgent &&
    !startedSession`, hides both buttons for every message once the chat has
    started a run. Restore them for the chat turns after the run start, and
    for turns before it where revising is safe. Where an action truly isn't
    available, show it disabled rather than hiding it. The comment in
    `chat_timeline_message_actions.tsx:66` says the opposite; update it.
11. **Mobile interview question is cut off.** On a phone (iOS Safari), a
    multiple-choice interview question with long options ("Immune relay",
    "Open to mechanisms", "Type your own answer", "Send answer") fills the
    screen. The question text is hidden above the fold and the page won't
    scroll. Reproduce it at 375×812 in Playwright with a long-option
    interview, then make the card scroll (or cap its height) so the whole
    question and the composer are reachable.

## Phase 3 — Chat sees the whole run

12. Mid-run, the chat answered "4 hypotheses generated … No detailed
    hypothesis text or evidence is available in the current context" and
    refused to list the hypotheses. The chat must have access to **every
    input and output of the run**: goal, plan, interview answers, literature
    and evidence, hypotheses (including mid-run), reviews, tournament
    matches, meta-review and report. Likely cause: hypothesis rows are only
    written to the table in the finalize pass (see memory note
    "created_at is drain time"), so the chat context reads empty tables
    mid-run. Read from the latest checkpoint state while the run is active.
    Size the context deliberately (summaries plus retrieval or tool access,
    not dumping everything) and respect the spend caps.

## Phase 4 — Example runs

13. The three demo runs (Recents shows "Ferroptosis Sensitization in
    Pancreatic Cancer", "Adolescent Prefrontal Circuit Refinement" and a
    third) currently ship only their results. Turn each into a full chat:
    seeded transcript, plan card and run, so a visitor can open it, read the
    conversation and keep chatting. That also makes them reachable on mobile,
    where Recents isn't shown. Fixtures live in `app/app/seed/`
    (`demo_seed_data*`, `scenario.py`, `overview.py`); see the memory note
    "Demos are curated, not generated".
14. Prefix their titles with `Example: `.

## Phase 5 — Landing page

15. **Trailer:** embed https://www.youtube.com/watch?v=Wnhe8a8kKc0 in the hero.
    The empty space is below the "Start a research goal / See how it works"
    buttons, left of the DNA illustration, above the section tabs. Use
    youtube-nocookie, lazy-load it and keep it responsive.
16. **One sticky bar:** today the top bar ("Co-Scientist" left,
    "Feedback" and "Logs" right) and the section tabs (Overview · How it works ·
    Tournament · Evidence · Safety · Tiers · FAQ) stick as two stacked rows.
    On scroll, the tabs should join the top bar, centred between the logo and
    the right-hand buttons, as a single row. Handle narrow widths (the tabs may
    need to scroll horizontally or collapse).
17. **Uneven cards:** in the three "You write / The agents / You get" cards,
    the fills look uneven. The left inner card is tall, the middle list stops
    short and the right card leaves empty space below its "#2/#3" rows. Make
    the three inner panels share height and fill evenly (stretch or
    distribute the content so the bottoms align).

## Phase 6 — Feedback form beside Logs

18. Add a **Feedback** pill to the left of the "Logs" pill (top-right of the
    workbench and landing page). Its glyph is the Material Symbols `stars`
    icon (a star in a circle), the one the old SBI pilot feedback button
    used; it is already in `components/icon.tsx`. It opens a centred modal
    like the Settings view: a category dropdown and a message textarea, with
    Submit and Cancel.
19. **Categories** (decided, in this order): Bug · Security · Results
    quality · Feature request · Other. The logs, URL and run ID give the rest of the context,
    so don't add more buckets.
20. Each submission silently attaches the session's diagnostic logs (today's
    Logs export: preamble, session details, stats, records), the current URL
    and the run ID if there is one. The user never sees the logs. Store the
    submission server-side, owner-scoped, with a way for the maintainer to
    read it (an admin endpoint behind the existing `LOGS_ADMIN_TOKEN`, and/or
    an email through the working Resend SMTP). Rate-limit it, and keep the
    store bounded (see "Prod volume + checkpoint leak").
21. **Logs must capture more**, now that they feed feedback: chat turns
    (role, length and timing, not full text unless small), tool calls,
    failed fetches and their status, modal opens, run-stage transitions with
    durations, and provider retry and escalation events. Keep the
    10-minute de-dup and the WARNING floor for per-call HTTP chatter.
22. Keep the Logs pill and its panel unchanged for now (decided). Note: an
    earlier feedback form was removed on 2026-08-27 along with the audience
    feature; don't revive that code. This is a new, simpler feature.
