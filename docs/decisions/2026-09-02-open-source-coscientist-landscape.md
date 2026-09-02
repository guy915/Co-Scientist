# ADR: Open-source Co-Scientist landscape — fork/mine/inspect/reject verdicts

**Status:** Accepted · 2026-09-02
**Source:** `docs/CORPUS-EXTRACTION.md:771` (corpus row R9-2), drained from
`references/core/google-co-scientist/build-methodology-*.md` §7 before that
reference is deleted — see the `references/peripheral/` precedent
(`docs/decisions/2026-08-23-chat-interface-reference-drain.md` and its three
sibling commits) for the shape this follows.

This record preserves a landscape survey's verdicts on the open-source
projects nearest to this one, so they survive `references/` deletion. It
stands alone: a reader who never sees the corpus row should understand every
decision below.

## Context

Early in this project's build methodology, a survey classified eight
open-source Co-Scientist-style or Co-Scientist-adjacent projects against a
four-way scale — **FORK PRIMARY** (adopt as the starting codebase), **MINE**
(read for technique, do not adopt the code), **INSPECT** (worth a closer
look before deciding), **REJECT** (not worth using). Those verdicts existed
only inside the corpus file being retired; nothing in `docs/` recorded them.

This repo was in fact **built independently** on FastAPI + LangGraph, not
forked from any of the eight — confirmed directly: no code from any of
these projects is vendored or present anywhere in this tree outside
`references/`. The two that are cited at all (Jataware, Sakana) appear only
in `README.md`'s Acknowledgements, as citations of prior art, not as
forked-from code.

## Decisions

| Project | Verdict | Notes |
| --- | --- | --- |
| Jataware `open-coscientist` | FORK PRIMARY | Not actually forked. Cited in `README.md`'s Acknowledgements as prior art |
| LLNL | MINE | Not otherwise referenced anywhere in this tree |
| Sakana AI Scientist v2 | MINE | Sakana AI Scientist (v1) is separately cited in `README.md`'s Acknowledgements; "v2" is the distinct, later project this survey verdicted here |
| FutureHouse Robin | MINE | Not otherwise referenced anywhere in this tree |
| OpenScientist/K-Dense | MINE | **Not** the same product as the tool-skills bundle vendored at `vendor/science-skills/`, whichever organization actually authored that bundle — `NOTICE` and `AGENTS.md` credit it to Google DeepMind (`google-deepmind/science-skills`), while `docs/decisions/2026-08-23-chat-interface-reference-drain.md:30` describes the same vendored path as `K-Dense-AI/scientific-agent-skills`; that attribution tension is unresolved here and is a separate question from this row. Either way, a Co-Scientist-*style agent* and a *tool-skills bundle* are two different products; the agent has not been inspected here |
| aimclub CoScientist | MINE | Not otherwise referenced anywhere in this tree |
| The-Swarm-Corporation `AI-CoScientist` | INSPECT | Already carried out, in more depth than "inspect" implies, by `docs/decisions/2026-08-23-chat-interface-reference-drain.md`'s "The namesake, head to head" section: the file was read in full (1993 lines, synchronous, in-memory, no durability) and compared feature-by-feature against this repo — same Elo init/K (1200/24, independently), but no dedup guard on repeated match pairs, evolved text overwrites the hypothesis in place with no lineage, fully in-memory with no crash recovery, and a free-text safety field nothing gates on. This repo is ahead on every one of those axes. No further inspection is warranted |
| mims-harvard `AutoScientists` | REJECT | Not otherwise referenced anywhere in this tree |

## Consequences

None of these verdicts require a code change — this ADR is a record, not a
task list. If any of the six MINE-verdict projects not yet read (LLNL,
Sakana v2, FutureHouse Robin, OpenScientist/K-Dense, aimclub CoScientist) is
worth a closer technique read later, this is the standing decision that
says so; nothing here is time-sensitive to `references/` deletion once this
file exists.
