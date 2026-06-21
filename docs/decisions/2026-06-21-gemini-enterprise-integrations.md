# ADR: Gemini Enterprise — viable integrations

**Status:** Accepted · 2026-06-21
**Drains reference:** `references/UI:UX/gemini-enterprise/`

Records what the co-scientist takes from Gemini Enterprise — the surface that
*hosts* Idea Generator (Idea Generation is an agent inside it). Stands alone so
the reference can be deleted.

## Context

Gemini Enterprise is a general-purpose enterprise chat shell: a left sidebar
(New chat, Search, Library; an **Agents** list — Idea Generation, NotebookLM,
Deep Research; a **Chats** list of past conversations with concise
auto-generated titles; Settings), a greeting home ("Hello, Guy — Let's get some
work done!"), a composer with tool toggles (Deep Research, Google Search, file
upload), settings/personalization, and an account switcher. Captures also
include its chat **system prompt** and a **chat-naming prompt**.

## Assessment against the co-scientist

The co-scientist is a focused hypothesis-generation tool, not a general
enterprise assistant. Most of Gemini Enterprise's surface is therefore out of
scope, and its home chrome is what Idea Generator (ref #6) already gave us.

| Gemini Enterprise element | Disposition |
| --- | --- |
| Home chrome (sidebar + greeting + composer) | already covered by the Idea Generator home (ref #6) |
| **"Chats" list with concise auto-titles** | **harvested** — the history/run list now shows a concise title instead of the full goal |
| Composer tool toggles (Deep Research, Google Search, upload) | out of scope — general-chat features, not research-run controls |
| Settings / personalization / memory / account switcher | out of scope — local-first, single-user |
| Multi-agent launcher (Idea Generation / NotebookLM / Deep Research) | out of scope — the co-scientist *is* the single agent |
| Chat system prompt / chat-naming prompt | informs our Q&A and the concise-title heuristic |

## Decisions

1. **Harvest the concise-title pattern.** A `conciseTitle()` helper
   (`src/lib/text.ts`) shortens a research goal into a single-line title
   (first clause, word-boundary truncation, ellipsis), used in the history
   sidebar — mirroring the Gemini Enterprise "Chats" list (the full goal stays
   available as a hover tooltip). A heuristic, not an LLM call, to stay cheap
   and offline. (Built; unit-tested.)
2. **Decline the general-chat surface** (composer tool toggles, settings,
   personalization, account switcher, multi-agent launcher) — out of scope for
   a focused research tool.

## Consequences

- The run/history list reads cleanly like the Gemini Enterprise "Chats" list.
- No drift toward a general enterprise assistant.
- The reference can be deleted at cleanup; this ADR records the assessment.
