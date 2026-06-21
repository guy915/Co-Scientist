# ADR: Idea Generator UI/UX replication

**Status:** Accepted · 2026-06-21
**Drains reference:** `references/UI:UX/idea-generator/`

Records how the co-scientist workbench adopts Google's **Idea Generator** UI/UX.
Stands alone so the reference can be deleted.

## Context

Idea Generator (an agent inside Gemini Enterprise) and Co-Scientist are
**siblings**: Idea Generator is the business-targeted clone of the same
multi-agent tournament UI/UX. It is the **UI/UX main character** — the
co-scientist's interface should match it, retargeted from business "ideas" to
scientific "hypotheses."

Idea Generator's flow: **home** ("Create a multi-agent innovation session" — a
labeled header, a 3-step explainer, prompt-suggestion chips, a prominent input,
and a Recents panel) → **session-setup** (the agent drafts a Goal + Requirements
spec the user reviews/edits, then "Start session") → generation + tournament →
**ideas-results** (results overview + idea detail).

The co-scientist already shares this shape: a chat-first workspace
(`chat_workspace.tsx`) where the user enters a goal, an inferred run-spec card
(Goal/Mode/Constraints/Output) is reviewed/edited, then **Start** launches the
run; results show in the run-detail tabs. The design language is already
Material (Google Sans + an MD3 teal theme), so the gap was *layout/structure*,
not tokens.

## Decisions

1. **Replicate the signature home.** The home empty state now mirrors Idea
   Generator: a teal "Hypothesis generation" label (with a science glyph), the
   headline "Create a multi-agent research session", and a 3-step explainer —
   **Getting started → Hypothesis generation → Evaluation and ranking
   (tournament-style)** — above the prompt input and science suggestion chips.
   (Built; visually verified at mobile and desktop widths.)

2. **Keep the existing session-setup and results as the sibling
   implementation.** The inferred run-spec card + "Start" gate is the
   co-scientist's version of "review the draft, then Start session"; the
   run-detail tabs (Ideas / Tournament / Summary) are its results surface. These
   are structurally faithful and on-brand; no rebuild needed.

3. **Retarget wording to science** ("research session", "hypotheses") rather
   than business "ideas", per the main-character guidance.

4. **Defer further pixel-polish to refs #7/#8** — viable integrations from
   Gemini Enterprise (#7) and Gemini (#8), then final adjustments from the
   co-scientist live-footage videos (under `references/core/.../media/
   live-footage/`).

## What was built

- `chat_workspace.tsx`: the home empty state gains the Idea-Generator label,
  headline, and a `SESSION_STEPS` 3-step explainer (numbered MD3 chips), kept
  above the existing Composer + suggestion chips. Lint/build/tests clean;
  screenshots confirm parity with the reference home (light/dark via the theme).

## Consequences

- The co-scientist's entry screen now reads as the Idea Generator's sibling.
- Recents are available via the existing History panel rather than a separate
  home panel (a possible future enhancement).
- The reference can be deleted at cleanup; this ADR records the mapping.
