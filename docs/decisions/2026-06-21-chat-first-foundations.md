# ADR: Chat-first foundations for the Co-Scientist workbench

**Status:** Accepted · 2026-06-21
**Drains reference:** `references/core/ai-chatbot-interface/`

This record captures what we take from the "best OSS foundations for a
chat-first AI co-scientist" survey so that the 60 KB report can be deleted
without losing the decisions. It stands alone: a reader who never sees the
report should understand every choice below.

## Context

The survey argues that a research-conversation product is *not* a generic
chatbot. Its transferable principles: keep the conversation central with
structured side panels; **stream visible intermediate work** (agent progress,
tool calls, state) into the UI; model research as scope → research → write;
ground answers in scientific literature with first-class citations; treat
hypotheses as first-class, versioned objects. Its concrete product picks were
LibreChat (fork), CopilotKit + AG-UI (stream state), Open Deep Research
(run orchestration), PaperQA2 + Docling (ingestion), Qdrant (vectors),
Citation.js / Quarto (citations + export).

Our system already realizes the co-scientist's distinctive loop — a supervised
multi-agent pipeline (generate → review → tournament → evolve), Elo-1200
pairwise ranking, deep verification, a meta-review feedback loop, research
overview / NIH Specific Aims, citation classification, and a fail-closed
safety gate — on a React + FastAPI + SQLite stack with an append-only event
log and SSE replay.

**Co-Scientist is the main character.** This reference is secondary: it may
sharpen the co-scientist's chat experience but must not turn the product into a
generic chatbot.

## Decisions

1. **Keep the stack.** We do **not** fork LibreChat, swap to CopilotKit/AG-UI,
   or adopt Qdrant/PaperQA2/Docling. We adopt the report's *patterns*, not its
   products. Rationale: our stack already carries the co-scientist's
   differentiators; a rewrite would cost more than it returns and would not
   make the science better.

2. **Adopt "citation-grounded answers."** The Chat tab's Q&A now feeds the
   run's own evidence into the prompt and renders inline `[n]` references that
   resolve to the classified evidence. This welds the chat to the evidence
   pipeline that is already a differentiator. (Built — see below.)

3. **Adopt "streamed structured intermediate state."** Every pipeline event now
   carries a current leaderboard snapshot, and the run view shows live
   standings (forming hypotheses + Elo) while a run is active — the report's
   headline pattern, realized without changing stacks. Necessary because the
   engine only persists hypotheses at completion, so mid-run state is otherwise
   invisible. (Built — see below.)

4. **Decline generic chat plumbing:** multimodal chat, conversation-history
   search, and chat-driven run-parameter tuning. They fail the main-character
   test (generic chatbot features that do not amplify the co-scientist loop).

## Routing (themes that belong to later references)

These survey themes are real but are the domain of references not yet drained.
They are recorded here so those drains pick them up rather than this one
duplicating or pre-empting them.

| Theme | Routed to |
| --- | --- |
| Goal scoping / "approve the plan before the run" | `UI:UX/idea-generator` (#6) — its session-setup + "Start Tournament" gate |
| Bring-your-own documents / scientific-document grounding (PaperQA2/Docling) | `peripheral/antigravity-science-skills` (#4) |
| Citation export depth (Citation.js / Quarto / nbconvert) | `peripheral/notebooklm` (#5) |

## What was built

- **Citation-grounded Q&A.** `app/app/runs.py` `ask_question` builds a numbered
  evidence manifest (`_build_evidence_manifest`), injects it into the prompt,
  emits a `sources` SSE event, and persists the manifest as message `meta`
  (new `messages.meta_json` column in `app/app/store.py`). The frontend
  (`chat_tab.tsx`) renders `[n]` chips and a Sources footer, reusing the
  shared citation-state colors (`workbench/lib/citation_styles.ts`).
- **Live standings.** Each engine/mock event carries a unified leaderboard
  (`engine_adapter._live_leaderboard`, `mock_workflow._mock_leaderboard`); a
  pure selector (`workbench/lib/live_state.ts`) picks the latest snapshot and
  the Overview tab renders a "Live standings" panel for active runs.

## Consequences

- The chat is now evidence-grounded and the run view shows live progress, with
  no new infrastructure or dependencies.
- Plan-approval, document ingestion, and export depth are deferred to the
  references that own them (#6/#4/#5).
- The `references/core/ai-chatbot-interface/` report can be deleted at cleanup;
  this ADR preserves its actionable conclusions.
