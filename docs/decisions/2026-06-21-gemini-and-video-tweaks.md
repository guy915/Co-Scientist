# ADR: Gemini polish + Co-Scientist video tweaks

**Status:** Accepted · 2026-06-21
**Drains references:** `references/UI:UX/gemini/` and the live-footage videos in
`references/core/google-co-scientist/media/live-footage/`

Final UI/UX pass: polish from the public Gemini site, then authoritative
adjustments from the real Co-Scientist screen recordings. Stands alone.

## Context

Two sources remained after replicating Idea Generator (ref #6) and harvesting
Gemini Enterprise (ref #7):

1. **Gemini** (`gemini.google.com`) — the official, more-frequently-updated
   site (home + deep-research pages).
2. **Co-Scientist live footage** — two screen recordings of the *actual*
   Co-Scientist product (run-setup walkthrough; plan generation + execution).
   These are the highest-fidelity source for "the real text/icons differ a
   little" final tweaks.

## What the videos showed (authoritative)

Frames extracted with ffmpeg revealed the real Co-Scientist home, which differs
from Idea Generator's wording:

- Label: **Co-Scientist** (not "Idea Generation" / "Hypothesis generation").
- Headline: **"Drive novel scientific discovery with Co-Scientist."** (not
  "Create a multi-agent innovation/research session").
- The three steps are **Pick a research goal / Generate hypotheses / Evaluate
  and rank**, with this exact copy:
  1. "Tell Co-Scientist what you plan to research, point it to relevant data,
     and set your evaluation criteria."
  2. "A team of agents will generate ideas on your topic using their available
     data."
  3. "The agents will evaluate the ideas against your criteria and rank them,
     tournament-style."
- Session-setup shows a drafted plan with criteria (correctness/novelty/impact),
  a focus selector (evidence / novelty / balance / breakthrough), a tier
  selector (Explore / Express / Standard), and a "Start session" button — the
  structure our inferred run-spec card + Start gate already mirrors.

## Decisions

1. **Apply the video text to the home** (built): the home label, headline, and
   3-step copy now match the real Co-Scientist product exactly. Visually
   verified against the extracted video frame.
2. **Gemini site polish — examined, deferred.** The Gemini home/deep-research
   pages are general-assistant chrome; the co-scientist-specific authority is
   the live footage, which we applied. No additional Gemini-specific changes
   were warranted for a focused research tool.
3. **Session-setup criteria/focus/tier** (from the execution video) is a
   potential future enrichment of the run-spec card; recorded as future work,
   not built (the current Goal/Mode/Constraints card + Start gate is faithful
   to the flow).

## Consequences

- The home reads as the real Co-Scientist product, not just its sibling.
- Both references can be deleted at cleanup; this ADR records the authoritative
  wording and the deferred session-setup enrichment.
