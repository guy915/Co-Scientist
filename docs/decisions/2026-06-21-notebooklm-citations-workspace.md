# ADR: NotebookLM citations + workspace — assessment

**Status:** Accepted · 2026-06-21
**Drains reference:** `references/peripheral/notebooklm/`

Records what we take from the NotebookLM reference (architecture spec + UI
captures). Stands alone so the reference can be deleted.

## Context

NotebookLM is a **source-grounded RAG notebook**: a user curates a set of
documents, then chats over them with strict inline citations, and generates
multi-format deliverables. Its UI is a three-column workspace — **Sources**
(left: add/curate/sync documents), **Chat** (center: grounded answers with
inline hover-to-source citations and a "N sources" indicator), **Studio**
(right: Audio/Video Overview, Slide Deck, Mind Map, Reports, Flashcards, Quiz,
Infographic, Data Table).

## Assessment against the co-scientist

The co-scientist is **not** a source-curation notebook. It autonomously
generates and tournaments hypotheses, and follows Idea Generator's UI/UX (the
UI/UX main character — refs #6–8). So most of NotebookLM's surface is a
different product paradigm.

| NotebookLM pattern | Disposition |
| --- | --- |
| Inline citations grounded in sources, traceable to origin | **Already realized** — ref #2 added citation-grounded Q&A with `[n]` chips, a Sources footer, and four-state citation classification (verified/partial/unsupported/unavailable). |
| "N sources" grounding indicator | **Harvested** (small) — the Sources footer now shows the cited-source count (`Sources (N)`). |
| Three-column Sources/Chat/Studio workspace | **Out of scope** — user document curation is not the co-scientist's model (it retrieves evidence autonomously), and the layout would conflict with the Idea-Generator-styled UI. |
| Studio multi-format outputs (podcasts, slides, mind maps, quizzes) | **Out of scope** — the co-scientist's deliverable is a hypothesis report + NIH Specific Aims, not study aids. |
| Notes-as-sources / bidirectional sync with Gemini | **Out of scope** — no user-source corpus to sync. |

## Decisions

1. **Citation grounding is done** (ref #2); no rework needed.
2. **Harvest the "N sources" indicator** onto the grounded-answer Sources
   footer — a faithful, non-conflicting touch that sharpens the citation UX.
3. **Decline the source-curation workspace and Studio outputs** — different
   product paradigm; the co-scientist's UI follows Idea Generator.

## Consequences

- The grounded-answer UX gains an explicit source count.
- No paradigm drift toward a notebook/source-curation product.
- The NotebookLM reference can be deleted at cleanup; this ADR preserves the
  assessment and the one harvested pattern.
