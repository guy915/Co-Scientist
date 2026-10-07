# Duplication audit

**Question.** Is the same concept implemented more than once, in different
ways, across the codebase?

**Answer.** It depends on the layer. The frontend UI layer has the problem
throughout. So do the MCP server's tool layer and the test doubles. In the
backend cores (LLM transport, SQLite access, task queue, SSE framing, Elo math,
JSON repair) each concept has one implementation that everything uses. There,
the duplication sits in the small helpers around those cores. Exact copy-paste
is rare everywhere: 0.08% of production lines at 6 lines/60 tokens. The real
pattern is the same concept written again from scratch, differently.

13 of the duplicates are severity A: users see different behaviour, or
correctness is at risk. They are separate fixes, not refactors. No area needs
a rewrite. The frontend needs a shared UI kit built and adopted (frontend lane
Part 1). Everything else is targeted consolidation in refactor phase 5.

- **Scope:** `app/`, `engine/` (including `engine/mcp_server/`),
  `evaluations/`, `e2e/`, and the build and CI configuration. `vendor/` is
  excluded.
- **Revision:** `main` at `a5dfe06`. Every `path:line` reference is to that
  revision. Up to `4ad5448`, the only cited code file that later commits
  touched is `app/frontend/src/workbench/layout_nav_rail.tsx`: on `main` its
  references from line 100 on sit 3 lines lower, and the inline `700px`
  media-query count drops from 144 to 143.
- **Target structure:** the plan in `docs/REARCHITECTURE.md`, with the
  package names that ADR-001 (`docs/adr/001-module-map.md`) settled. Where
  ADR-001 places a module, its placement wins. For example, the feedback
  admission budgets in A-09 belong to `domains/feedback`. The audit changed
  no code.

## Contents

1. [Method](#method)
2. [Calibration](#calibration)
3. [Summary by area](#summary-by-area)
4. [Findings, severity A](#findings-severity-a)
5. [Findings, severity B](#findings-severity-b)
6. [Findings, severity C](#findings-severity-c)
7. [Intentional differences](#intentional-differences)
8. [Clean concepts](#clean-concepts)
9. [Other observations](#other-observations)
10. [Blind spots of this method](#blind-spots-of-this-method)
11. [Verdict per area](#verdict-per-area)
12. [Overall answer](#overall-answer)

## Method

Five passes, run on 7 October 2026 after `make setup`.

1. **Clone detection.** I ran jscpd 4.3.0 at 6 lines/60 tokens and at 4
   lines/40 tokens. I ran it on each area's production files and test files
   separately, then on all production files and all test files together, so
   that cross-area clones show up. For Python I also ran pylint's `symilar`
   (pylint 4, ignoring comments, docstrings, imports and signatures) at 6 and
   4 lines. The generated frontend `wire_*.ts` files (501 lines) are excluded
   from the frontend production count, because they are a build product.
2. **Structure-based.** Every Python function and every TypeScript or TSX
   function, arrow function and method was turned into an AST. All
   identifiers, literals and type annotations were replaced by placeholders,
   and the AST was hashed. I listed the groups of the same shape in different
   files, at minimum sizes of 40, 25 and 15 nodes for Python and 40 and 20 for
   TypeScript.
3. **Name-based.** I collected 3,397 Python and 974 TypeScript production
   function names and normalized the synonymous verbs:
   - normalize, clean, sanitize, strip
   - parse, extract, coerce
   - format, render, display
   - fetch, load, get
   - score, rank, rate
   - truncate, clip, excerpt, cap

   I then grouped names by verb class and object across modules. I also made
   per-concept listings: tokenize, similarity, truncation, text
   normalization, time, duration, hashing, DOI/PMID, retry, dedup, plural.
4. **Literal values.** These passes looked for literals written in several
   places instead of named once:
   - Python AST constants: numbers, URLs, model ids, env-var names, used in 3
     or more files, counting named definitions against inline uses.
   - Environment variables read in more than one file.
   - Frontend hex colours, arbitrary Tailwind values (radii, font sizes,
     spacing, z-index), media queries, durations and easings.
5. **Concept by concept.** Seven Sonnet subagents worked in parallel, one per
   area:
   - engine platform
   - engine science
   - app backend
   - MCP server plus cross-cutting concerns
   - frontend UI
   - frontend logic
   - tests

   Each one found every implementation of the concepts on the brief's list,
   read them, and recorded the fields this report uses. I then re-checked
   every severity-A claim myself, by reading the code or running the
   functions in the project venv; the A list says which. One A claim I first
   downgraded turned out to be right, and is restored (A-06).

Severity:

- **A:** users see inconsistent behaviour, or correctness is at risk.
- **B:** a maintenance hazard.
- **C:** cosmetic.

"Lines saved" is always a count of the redundant lines (`sed -n a,bp | wc -l`
on the cited ranges). It is an upper bound, before adding back the shared
version, unless the entry says "net".

"Belongs" uses three labels:

- **phase 5:** the "deepen" phase of the re-architecture plan.
- **frontend lane Part 1:** the frontend shared-kit work that Lane F does
  before phase 7. The plan does not define this term, so this is my reading
  of the brief.
- **separate fix:** worth doing on its own, before launch.

## Calibration

The brief required the method to rediscover the known frontend button
finding. The first two passes missed it.

- jscpd found 0.03% duplication in frontend production code at 6 lines/60
  tokens.
- The structural hash found 4 cross-file groups at 20 nodes, none of them
  buttons.

Buttons are inline JSX elements with hand-written class strings, not
functions, so clone and shape detectors cannot see them. I fixed the method
by adding an element-level pass: parse every TSX opening tag and collect its
tag, attributes and class expression. That pass reproduces the finding
exactly.

| Measure | Brief | This audit |
|---|---|---|
| `<button>` elements in production TSX | about 50 | **50** |
| Files containing them | 23 | **23** |
| Shared `Button` component | none | none; a few class-string constants in `app/frontend/src/workbench/classes.ts:39,48` serve 8 buttons |
| Distinct `className` expressions | – | **45** |
| Radius utilities on buttons | "mixed" | **7**: `rounded-full`, `rounded-[9999px]` (the same value spelled differently), `rounded-md`, `rounded-xl`, `rounded-lg`, `rounded-[0.75rem]` (equals `xl`), `rounded-[1rem]` |
| Colour utilities on buttons | "near-miss" | **34**, from 3 token families (`cosci-*`, `th-*`, and the landing page's `--l-*`) |

Two counts differ by method. Counting only literal class strings gives 14
`rounded-full` and 4 `rounded-[9999px]`. Resolving class constants gives 24
and 10.

The same element-level and literal passes then found the wider frontend
design-system findings: B-40 to B-49 and C-16 to C-26.

Calibration lesson for every other area: clone percentages near zero do not
mean "no duplication". Every A finding in this report was found by the name
or concept passes. None came from a clone detector.

## Summary by area

Line counts are from `wc -l` on tracked `.py`, `.ts`, `.tsx`, `.css`,
`.js` and `.mjs` files.

- **Clone columns:** jscpd duplicated-line percentages, with production
  files and test files measured separately.
- **symilar column:** pylint's `symilar` on Python production code, at 6 and
  4 lines.
- **Concepts checked:** what each area's auditor reported; the counts
  overlap between auditors.
- **Findings:** each of the 121 findings is counted once, in the area where
  its fix would mainly live. The A, B and C columns add up to the
  "concepts with >1 implementation" column.

| Area | Production lines | Test lines | Clones, production, 6/60 | Clones, production, 4/40 | Clones, test, 6/60 | Clones, test, 4/40 | symilar, Python production, 6 / 4 | Concepts checked | Concepts with >1 implementation | A | B | C | Measured redundant lines |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Engine (`engine/src`) | 36,262 | 12,730 | 0.04% | 0.46% | 0.20% | 0.97% | 0.10% / 0.26% | 83 | 29 | 3 | 16 | 10 | 724 |
| App backend (`app/app`) | 30,778 | 22,491 | 0.06% | 0.35% | 0.09% | 0.76% | 0.05% / 0.10% | 43 | 19 | 4 | 13 | 2 | 476 |
| MCP server (`engine/mcp_server`) | 3,544 | 1,712 | 0.00% | 0.51% | 0.00% | 0.00% | 0.00% / 0.17% | 18 | 8 | 2 | 6 | 0 | 518 |
| Frontend (`app/frontend/src`, without the generated `wire_*.ts`) | 23,963 | 6,048 | 0.03% | 0.12% | 0.29% | 1.08% | – | 74 | 39 | 4 | 18 | 17 | 784 |
| Evaluations | 1,600 | 759 | 0.00% | 0.94% | 0.00% | 0.00% | 0.00% / 0.00% | (covered by other areas) | 0 | 0 | 0 | 0 | 0 |
| E2E (`e2e/`) | – | 1,496 | – | – | 0.00% | 2.01% | – | (in Tests) | – | – | – | – | – |
| Build and config (Dockerfiles, Makefiles, CI, env examples, pyprojects) | – | – | not measured | not measured | – | – | – | 26 | 7 | 0 | 4 | 3 | 148 |
| Tests (all suites; findings only) | – | (rows above) | – | – | – | – | – | 35 | 19 | 0 | 13 | 6 | 773 |
| **All areas** | **96,147** | **45,236** | **0.08%** | **0.39%** | **0.21%** | **0.97%** | **0.18% / 0.34%** | about 290 | **121** | **13** | **70** | **38** | **3,423** |

The "All areas" clone figures come from running each tool once over all
production files and once over all test files, so they include clones that
cross areas. That is why the Python `symilar` total (0.18%) is higher than
any single area. The cross-area clones it found include:

- the URL guard (`app/app/pinned_http.py:24-45` and
  `engine/mcp_server/safe_http.py:28-49`)
- `app/app/claims/assessor.py:59-70` and
  `engine/src/co_scientist/offline/llm.py:103-114`
- `app/app/engine_adapter/drain/reviews.py:158-173` and
  `engine/src/co_scientist/schemas/review.py:276-287`

The structural hash found 12 cross-file Python groups (90 lines) and 4
TypeScript groups (49 lines) at its smallest thresholds. Every group is
covered by a finding or is trivial (for example, one-line `__init__`
methods).

## Findings, severity A

Each entry gives its verification status:

- **Reproduced:** I ran the functions in the project venv.
- **Read:** I confirmed it by reading the code.
- **Auditor-read:** a subagent read it, and I checked only part of it.

### A-01 Safety policy: two regex families that disagree, and the final screen uses only the weaker one for some hazards

- **Implementations:**
  - Hypothesis tier: `engine/src/co_scientist/safety.py:17-120`, with
    `review_hypothesis_safety` at `safety.py:397`.
  - Content tier: `safety.py:134-151`, with `review_content_safety` at
    `safety.py:233-265`.
  - `app/app/safety/__init__.py:309-313` `screen_intake` runs both tiers and
    takes the more severe result. `app/app/safety/__init__.py:316-319`
    `screen_final` runs the content tier only.
  - Verdict vocabularies:
    - `SafetyOutcome` (`safety.py:159-165`)
    - the `ContentSafetyReview` strings (`safety.py:217`)
    - `SafetyDecision` (`app/app/safety/types.py:13`)
    - the semantic categories (`app/app/safety/semantic.py:54-62,92-98`),
      which use `redacted`/`allowed` against `redact`/`allow` elsewhere.
- **Difference:** behaviour. Reproduced:

  | Text | Content tier | Hypothesis tier |
  |---|---|---|
  | "synthesize sarin" | block | allow |
  | "produce fentanyl at kilogram scale" | block | allow |
  | "smuggle a nuclear device" | allow | prohibited |
  | "weaponize the pathogen" | allow | prohibited |

  The same hazard family is written twice with different verbs. Each tier
  misses cases the other catches. The app patches this at intake only, so
  the final report screen misses the second pair.
- **Single version:** `domains/safety/`, as one rule table that feeds the
  hypothesis review, intake and final screen.
- **Lines saved (measured):** 67 (`safety.py:134-151` is 18 lines;
  `safety.py:217-265` is 49).
- **Risk:** high. This is the safety policy itself.
  - `POLICY_VERSION` (`safety.py:154`) is persisted with each decision.
  - No existing block may loosen.
  - Safety tests need re-baselining.
- **Belongs:** separate fix (at least run the hypothesis tier in
  `screen_final`), then phase 5.
- **Verified:** reproduced.

### A-02 Which hypothesis fields are screened and redacted: the engine and the app pick opposite fields

- **Implementations:**
  - Engine screen and redaction:
    - `engine/src/co_scientist/agents/safety.py:35-41` screens `text`,
      `explanation` and `experiment`.
    - `engine/src/co_scientist/safety.py:407-416` redacts `explanation` and
      `experiment`.
  - App screen and redaction:
    - `app/app/hypothesis/__init__.py:27-32` screens `statement`,
      `mechanism`, `expected_effect` and `experimental_context`.
    - `app/app/hypothesis/__init__.py:47` redacts `mechanism` and
      `experimental_context`.
    - `app/app/hypothesis/safety.py:84-90` has a third set:
      `{mechanism, experiment, experimental_context}`.
    - `app/app/store/hypotheses.py:176` has a fourth list of redactable
      columns.
  - The legacy report gate (`app/app/report/gates.py:226`) screens
    `statement` only.
  - The engine-to-store field map is written twice:
    `app/app/engine_adapter/drain/hypotheses.py:334-336` and
    `app/app/qa/snapshot.py:62-72`.
- **Difference:** behaviour. The map turns engine `literature_grounding`
  into app `mechanism` and engine `explanation` into app `expected_effect`.
  So:
  - The engine redacts `expected_effect` and keeps `mechanism`.
  - The app redacts `mechanism` and keeps `expected_effect`, "so the
    high-level idea stays rankable" (`hypothesis/__init__.py:44-46`).
  - The engine never screens `literature_grounding` at all.

  The same REDACT verdict hides different text depending on which screen
  fired.
- **Single version:** `domains/safety/hypothesis_text.py`, as one table
  that maps each field (engine name, store name) to "screened" and
  "redacted". The field map belongs in `domains/research_state`.
- **Lines saved (measured):** 15. This counts the three redaction lists and
  the second field map; the value here is correctness, not size.
- **Risk:** high.
  - Screened sets must not shrink (`docs/OPERATIONS.md:88-93`).
  - Sticky safety statuses are persisted (`hypothesis/__init__.py:38-43`).
- **Belongs:** separate fix, after the owner decides the canonical field
  set; then phase 5.
- **Verified:** read, including the field map.

### A-03 Publication order of hypotheses: three implementations, two different orders

- **Implementations:**
  - Engine `rank_by_elo` (`engine/src/co_scientist/models/__init__.py:356-364`)
    sorts by Elo, then score, then text, all descending.
  - Engine `rank_for_publication` (`models/__init__.py:367-371`) moves
    undermined ideas last. It is used for the research overview's "top
    hypotheses" (`agents/meta_review/research_overview.py:300`) and by
    `ranking_lifecycle.py:151`.
  - App `rank_for_publication` (`app/app/elo.py:26-44`) puts undermined
    ideas last, then unplayed ideas after played ones, then sorts by Elo;
    ties keep store order. It is used for the report
    (`app/app/report/build.py:132,160`) and the live leaderboard
    (`elo.py:47`).
  - Frontend `sortByEloDesc` (`app/frontend/src/lib/hypotheses.ts:20-29`)
    follows the app rule. It is used when the report has no leaderboard
    (`run_detail_overview.tsx:68`).
  - `app/app/engine_adapter/events.py:60` sorts the meta-review `top_k` by
    raw Elo only.
- **Difference:** behaviour. Take idea A at Elo 1200 that has never played
  and idea B at 1184 that has played. The engine lists A first; the app and
  the frontend list B first. Ties are broken differently too. So the
  research overview's narrative and the report leaderboard can order the
  same run differently, although the docstring at `elo.py:29-31` says
  "Every reader-facing surface must use the same order".
- **Single version:** one `rank_for_publication` in
  `domains/research_state/`. The frontend should use the server's order
  rather than re-sort.
- **Lines saved (measured):** 31 (`elo.py:26-44` is 19 lines, `events.py:60-61`
  is 2, `hypotheses.ts:20-29` is 10).
- **Risk:** choosing one rule changes either the overview prompt or the
  report order. The app's played-first rule is deliberate (`elo.py:33-36`),
  so the engine should probably adopt it.
- **Belongs:** separate fix.
- **Verified:** read, all three.

### A-04 Lexical tokenization and coverage: seven tokenizers and four stopword lists; the citation classifier is punctuation-sensitive

- **Implementations:**
  - Tokenizers:
    - `app/app/citations/__init__.py:304-324`: whitespace split, tokens
      longer than 3 characters, punctuation left attached. Thresholds 0.60
      and 0.30 at `:332-335`.
    - `app/app/claims/assessor.py:216-236`: regex `[a-z0-9]+`, tokens
      longer than 3 characters plus `aml`, concept aliases. Thresholds at
      `:178,183`.
    - `app/app/claims/assessor.py:239-248`: retrieval tokens.
    - `app/app/qa/manifest.py:323-324`: regex, longer than 3 characters.
    - `app/app/run_corpus.py:14-15`: regex, longer than 2 characters.
    - `engine/src/co_scientist/agents/proximity/proximity_graph.py:13-19`:
      whitespace split, no filter.
    - `engine/src/co_scientist/agents/reflection/deep_verification_evidence.py:117-118`:
      regex with `casefold`, no filter.
    - `evaluations/citation_usefulness_eval.py:152`.
  - Stopword lists:
    - `app/app/claims/assessor.py:10` (80 words)
    - `engine/src/co_scientist/offline/llm.py:25` (110)
    - `engine/src/co_scientist/agents/generation/literature_review/queries.py:148` (38)
    - `evaluations/citation_usefulness_eval.py:54` (40)

    Pairs of lists share only 21 to 38 words.
- **Difference:** behaviour. Reproduced with the claim "TP53 loss impairs
  apoptosis in colorectal tumour cells" against an abstract that contains
  every one of its words, next to commas and periods:

  | Scorer | Score |
  |---|---|
  | `citations._token_overlap` | 0.714 |
  | `claims.assessor._lexical_score` | 1.0 |
  | proximity `token_coverage` | 0.75 |

  The engine-science auditor's pair scored 0.40 (PARTIAL) against 1.0.
  `docs/OPERATIONS.md:64` says to sanity-check thresholds "by feeding it a
  document that literally contains the claim", and the citation classifier
  fails that test.
- **Single version:** one `tokenize(text, *, min_len, stopwords)` and one
  `coverage(a, b)` in a shared text-matching module (`domains/documents/` or
  `science/`). Thresholds stay per caller.
- **Lines saved (measured):** 82.
- **Risk:** thresholds were tuned against each tokenizer. Changing the
  citation tokenizer shifts citation states for new runs. The offline
  determinism tests depend on the alias map.
- **Belongs:** separate fix (citation tokenizer), then phase 5.
- **Verified:** reproduced.

### A-05 Citation-key extraction: the engine drops grouped keys that the app knows how to handle

- **Implementations:**
  - `engine/src/co_scientist/agents/generation/citations.py:162-177`
    extracts keys with `\[C\d+\]` (`:170`).
  - `app/app/engine_adapter/drain/reviews.py:15,51-68` accepts `[C1, C2]`
    groups.
  - The strip regex at `engine/src/co_scientist/constants/__init__.py:276-281`
    is a third rule.
- **Difference:** behaviour. Reproduced: `re.findall` returns only `[C3]`
  from "as shown [C1, C2] and [C3]".
  - The prompt asks for `[C2][C3]`
    (`prompts/templates/hypothesis_validation_synthesis_with_tools.md:103`),
    but `reviews.py:58-60` notes that models do group keys.
  - A grouped citation never enters `citation_map`, so it gets no persisted
    citation row, and the app's group handling never sees it.
- **Single version:** `science/citations`, as one `citation_keys_in(text)`.
- **Lines saved (measured):** 12.
- **Risk:** `citation_map` contents change in the generation tests.
- **Belongs:** separate fix.
- **Verified:** reproduced.

### A-06 Two PubMed parsers in the MCP server; one returns `"<not found>"` strings that merge distinct papers in the report

- **Implementations:**
  - `engine/mcp_server/pubmed_client.py:109-120` (DOI) and `:136-142`
    (abstract) return the literal string `"<not found>"`. This is pinned by
    `engine/mcp_server/tests/test_pubmed.py:94`.
  - `engine/mcp_server/tools/lit_review/search_pubmed.py:118-129,152-164`
    returns `None` for the same cases.
  - The downstream path:
    - `engine/src/co_scientist/evidence/search_support.py:154-155` passes
      the raw dict through.
    - `engine/src/co_scientist/evidence/article_support.py:95` copies it:
      `doi=metadata.get("doi")`.
    - `app/app/engine_adapter/drain/hypotheses.py:88` persists it.
    - `app/app/citations/__init__.py:242-243` tries the DOI first, so it
      resolves `https://doi.org/<not found>`.
    - `app/app/report/markdown/hypothesis.py:90-92,105-111` de-duplicates
      by DOI.
- **Difference:** behaviour. Reproduced:
  `build_article_from_metadata(..., doi="<not found>")` gives
  `Article.doi == "<not found>"`, and two different papers that both carry
  that DOI become one row in `_dedupe_evidence`.

  The two tools also sort differently (`pub_date` against relevance), and
  only one honours `recency_years`.
- **Single version:** one `mcp_server/pubmed_records.py` that parses once,
  with `None` for absent values. The engine should also treat the sentinel
  as missing.
- **Lines saved (measured):** 48.
- **Risk:** cached PubMed metadata files already contain the sentinel, so
  readers must tolerate both. `test_pubmed.py:94` changes.
- **Belongs:** separate fix, then phase 5.
- **Verified:** reproduced. I first downgraded this because the `tools.yaml`
  field mapping does not list `doi`. That was wrong: with `is_dict: true`
  the raw dict passes through unmapped.

### A-07 Retrieval failure looks like "no results": six failure conventions across 21 MCP tools, and an engine search path that hides errors

- **Implementations:**
  - Tools that return an empty result with no error marker:
    - `engine/mcp_server/tools/lit_review/arxiv_search.py:108-110`
    - `engine/mcp_server/tools/biomedical_databases.py:220-222`
      (ClinicalTrials.gov), `:256-258` (Ensembl), `:308-310` (gnomAD),
      `:377-379` (STRING), `:445-447` (Reactome), `:516-518` (Open Targets)
    - `engine/mcp_server/tools/web_providers.py:77-79`
  - Tools that return an error object: `biomedical_databases.py:39-53`
    (ChEMBL `:99`, UniProt `:154`). GWAS uses its own string error
    (`:558-575`).
  - Tools that raise: `europepmc_search.py:113-115`,
    `openalex_search.py:195-198`, `opencitations.py:163-165`.
  - A JSON error string: `search_pubmed.py:59-61`.
  - On the engine side, `engine/src/co_scientist/evidence/search_query.py:50,58-65,78-106`
    detects the FastMCP error envelope, retries, and records the failure.
    The novelty-validation path
    (`engine/src/co_scientist/agents/generation/literature_tools/validate.py:128,143`)
    makes a bare call and turns any exception into `{}` (`:233-239`).
    `engine/src/co_scientist/evidence/retrieval_support.py:288-307` treats
    an error text as a paper's full text.
- **Difference:** behaviour. An outage or a rejected query reads as "no
  papers" or "no trials" in 7 tools and in novelty validation. The
  literature-review path keeps the two apart. The intended rule is written
  down (`openalex_search.py:1-3`, and the AGENTS.md line "Evidence gates
  must distinguish missing, unsupported, contradictory, and unsafe
  findings"), but the code applies it in only some places.
- **Single version:** `mcp_server/tools/_results.py`, as one
  empty-or-failed contract for every tool. On the engine side,
  `platform/retrieval/`, with one `call_search_tool` that `validate.py` also
  uses.
- **Lines saved (measured):** 27 on the MCP side (three identical empty
  helpers and seven 3-line except blocks). The engine change is behavioural
  and saves nothing.
- **Risk:** turning silent-empty into raise changes engine retries
  (`search_query.py:84-106`), and adding retries multiplies MCP calls during
  an outage. This needs a decision per source.
- **Belongs:** separate fix.
- **Verified:** I read the arXiv tool and `validate.py`. The other tools
  are auditor-read.

### A-08 Q&A lacks the reasoning-only retry the other chat surfaces have, and reports every failure as a missing API key

- **Implementations:**
  - Three surfaces retry once with thinking off, each detecting the case
    differently:
    - `app/app/interviews/model.py:487-509` (any reasoning chunk seen)
    - `app/app/run_start_announcement.py:180-201` (reasoning text
      accumulated)
    - `app/app/goal_text.py:148-171` (`usage.reasoning_tokens`, `:191-195`)
  - `app/app/qa/__init__.py:137-178` has no such retry.
  - `_framed_answer` persists whatever was emitted (`qa/__init__.py:318`).
  - `_handle_qa_stream_error` (`qa/__init__.py:378-388`) answers every
    exception with "Q&A requires a language model API key".
- **Difference:** behaviour. A turn that reasons and writes nothing is
  retried in the interview but saved as an empty answer in Q&A. A Q&A
  timeout or provider outage tells the user to set an API key.
  `docs/OPERATIONS.md:71` documents the three copies as intentional (see
  [Intentional differences](#intentional-differences)). It does not cover
  Q&A.
- **Single version:** `platform/llm/stream.py`, as
  `stream_text(request, *, retry_on_reasoning_only)` that reuses the
  engine's usage parser (`engine/src/co_scientist/llm/request/response.py:28-45`).
- **Lines saved (measured):** 46. These are the two redundant retry blocks;
  B-20 covers the rest of the wrapper.
- **Risk:** the interview path emits a note to the reasoning stream, and
  the announcement path must still fall back to standby text.
- **Belongs:** separate fix (Q&A retry and error text), then phase 5.
- **Verified:** read. Not run against a provider.

### A-09 Four admission and rate limiters; the log-ingest one races

- **Implementations:**
  - `app/app/logs_api.py:22,33-57`: an in-memory sliding window over a
    module-level dict with no lock. It is called from `post_logs`
    (`@off_loop`, `:164-165`), which runs on a 4-thread pool
    (`app/app/async_bridge.py:84`).
  - `app/app/store/feedback.py:12-17,33-63`: a durable window that sends
    `Retry-After: 60` (`app/app/feedback_api.py:41-43`).
  - `app/app/free_usage.py:52-70`: a UTC day computed by `_day_bounds`.
  - `app/app/provider_usage.py:40-67`: a UTC day computed as
    `int(db._now() // 86400)`.
- **Difference:** behaviour.
  - `_check_rate` iterates over the shared dict and deletes keys while
    other handler threads insert into it. That can raise "dictionary
    changed size during iteration" and return a 500 for log ingestion.
  - Only feedback sends `Retry-After`; the five other 429 sites do not.
  - Two code paths compute "today".
- **Severity note:** A, but low impact: only client log ingestion is
  affected.
- **Single version:** `domains/access/admission.py`, with a sliding window
  backed by memory or SQLite, a daily budget, and one `Retry-After` policy.
- **Lines saved (measured):** about 24, net of the shared version.
- **Risk:** the feedback limiter must stay durable. The log limiter may
  stay in memory (`logs_api.py:20` explains the single-replica assumption)
  but needs a lock.
- **Belongs:** separate fix (the lock), then phase 5.
- **Verified:** read. Not reproduced.

### A-10 Browser storage access: no wrapper, and the most critical reads are the unguarded ones

- **Implementations:**
  - Unguarded:
    - `app/frontend/src/lib/client_id.ts:3-10` (`getClientId`, which every
      scoped request needs) and `:62`, `:69-86`, `:132`, `:137`, `:162-164`
    - `app/frontend/src/workbench/theme_context.tsx:27,74` (in the render
      path)
    - `app/frontend/src/workbench/hooks/chat_session_start_run.ts:288,343,354`
  - Guarded:
    - `workbench/layout_session_switch.tsx:163-185`
    - `workbench/layout_diagnostics.tsx:156-181`
    - `main.tsx:33-42`
    - `chat_session_start_run.ts:388-398`
  - The key `co_scientist_client_id` is written out a second time at
    `lib/error_tracking.ts:4`.
  - There are 12 key names across 4 prefix styles.
- **Difference:** behaviour. Where accessing `localStorage` throws (site
  data blocked, some webviews), `ThemeProvider` throws during render. The
  global error boundary then replaces the whole app, and `clientHeaders()`
  throws synchronously. The codebase states the rule itself: "Disabled/full
  storage must not block session navigation"
  (`layout_session_switch.tsx:185`).
- **Single version:** `src/shared/lib/safe_storage.ts` plus a key registry.
- **Lines saved (measured):** 70 lines of hand-rolled guarded access.
- **Risk:** key names are persisted in users' browsers, so do not rename
  them in the same change. The idempotency intent must fail explicitly,
  not silently.
- **Belongs:** separate fix (add the guards), then frontend lane Part 1
  (the wrapper).
- **Verified:** read.

### A-11 Menus and popovers: three outside-click implementations, and Escape works on one of four overlays

- **Implementations:**
  - Outside-click hooks:
    - `app/frontend/src/workbench/components/settings_dialog.tsx:602-617`
      (`pointerdown`)
    - `workbench/layout.tsx:346-365` (`pointerdown`, two refs)
    - `workbench/pages/chat_composer.tsx:425-447` (`mousedown`)
  - Escape is handled only in `SettingsSelect` (`settings_dialog.tsx:726-733`).
  - These have `role="menu"` but no Escape or arrow-key handling: the shell
    Settings popover (`layout_nav_rail.tsx:229-247`), the Logs popover
    (`layout_diagnostics.tsx`) and the Connectors menu
    (`chat_composer.tsx:650-673`).
- **Difference:** behaviour. Users can close one overlay with Escape and
  not the other three. Touch dismissal differs between `mousedown` and
  `pointerdown`.
- **Single version:** `src/shared/hooks/use_dismiss.ts` (outside click plus
  Escape) and `src/shared/ui/menu.tsx`.
- **Lines saved (measured):** 43.
- **Risk:** the layout listens only while a popover is open
  (`layout.tsx:344-345`), and that must stay. A menu inside a dialog must
  consume Escape before the dialog does.
- **Belongs:** frontend lane Part 1. Adding Escape is a small separate fix.
- **Verified:** read; neither `chat_composer.tsx` nor `layout_diagnostics.tsx`
  handles Escape.

### A-12 Copy feedback and toasts: four outcomes for one action, and two toast systems

- **Implementations:**
  - `app/frontend/src/lib/clipboard.ts:3-27` `copyText` swallows every
    failure and ignores the `execCommand` result (`:21`).
  - The four outcomes of a copy:
    - "Copied" label (`workbench/layout_diagnostics.tsx:36-51`)
    - icon swap with its own 2000 ms constant
      (`components/markdown_message_renderer.tsx:143-157`)
    - "Prompt copied" toast (`workbench/hooks/chat_session_handlers.ts:170-188`)
    - nothing at all for "Copy response"
      (`workbench/pages/chat_timeline_message_actions.tsx:80`)
  - The two toast systems:
    - `useToast` plus `ToastPortal` (`workbench/hooks/timers.ts:50-76`,
      `chat_workspace.tsx:172-193`): 3 s, bottom-left.
    - `RunToast` (`run_detail_shell.tsx:167-177`, state at
      `run_detail_data.ts:82-86`): red, bottom-right, never dismissed.
- **Difference:** behaviour. Copying a response gives no feedback. The
  other copy actions report success even when the copy failed. A run-page
  toast never goes away.
- **Single version:** `src/shared/ui/toast.tsx`,
  `src/shared/hooks/use_copy.ts`, and a `copyText` that returns whether it
  succeeded.
- **Lines saved (measured):** 46 (`RunToast` 11, its state 5, the
  renderer's copied flag 14, the diagnostics copied flag 16).
- **Risk:** tests assert the toast text, and the run page has no toast host
  mounted yet.
- **Belongs:** separate fix (feedback for "Copy response", and a success
  result from `copyText`), then frontend lane Part 1.
- **Verified:** read.

### A-13 Reduced-motion handling: three copies of the media query, and two places that ignore the preference

- **Implementations:**
  - The CSS gate in `app/frontend/src/index.css:420-431`.
  - `matchMedia` checks:
    - `workbench/pages/home_landing_hooks.tsx:7-26`
    - `workbench/pages/chat_timeline_bubble.tsx:342-349`
    - `workbench/pages/chat_home_stage.tsx:109-112`
  - Not gated:
    - `workbench/pages/chat_workspace.tsx:524` (`scrollTo` with
      `behavior: 'smooth'`)
    - `animate-ping` and `animate-pulse` at
      `workbench/pages/run_detail_activity_log.tsx:13,81,226`
- **Difference:** behaviour. Some motion honours the OS preference and some
  does not.
- **Single version:** `src/shared/hooks/use_reduced_motion.ts`.
- **Lines saved (measured):** 11.
- **Risk:** prerendering needs the `typeof window` guard.
- **Belongs:** separate fix (the two ungated places), then frontend lane
  Part 1.
- **Verified:** read (`chat_workspace.tsx:524`).

## Findings, severity B

Every finding here is severity B: a maintenance hazard, where copies must be
kept in step and drift is visible or likely. Findings are grouped by the
area where the fix would mainly live. Paths are relative to the repository
root. In the engine sections, `engine/src/co_scientist/` is shortened to
`co_scientist/`.

### Engine

#### B-01 Retry and transport policy is decided per call site, outside the one retry loop

- **Implementations:**
  - The LLM retry loop: `co_scientist/llm/attempts/retry.py:180-195,273-285`.
  - The search retry loop: `co_scientist/evidence/search_query.py:53-55,68-106`
    (4 attempts, jittered).
  - Europe PMC's own loop: `engine/mcp_server/tools/lit_review/europepmc_search.py:25-27,74-92`
    (fixed 0.5 s and 1.5 s delays, no jitter, wrapped again by the engine's
    loop).
  - Park jitter written out at `app/app/task_worker/outcomes.py:113`
    (`random.uniform(0, 15)`).
  - No retry at all: `orchestration.py:223,350`, `enrichment.py:33`,
    `queries.py:45`, `operations.py:171`, `research_adapter/__init__.py:296`.
- **Difference:** behaviour.
  - A transient MCP drop gets 4 attempts on search but 0 on full text, PDF
    discovery, enrichment and query generation.
  - `engine/AGENTS.md:255` says retrying "lives in exactly one place". That
    is true for LLM calls only.
- **Single version:** `platform/retrieval/` (`with_transient_retry`), built
  on the existing `co_scientist/backoff.py:4`.
- **Lines saved (measured):** 61 (search loop 39, Europe PMC loop 19,
  constants 3).
- **Risk:** the MCP server cannot import engine code. Its loop is
  intentional-looking (`europepmc_search.py:25`).
- **Belongs:** phase 5.

#### B-02 Decoding MCP tool results that may be JSON: six or seven decoders with different failure rules, and one latent crash

- **Implementations:**
  - `co_scientist/tools/provider.py:17-28` raises.
  - `co_scientist/tools/response_parser.py:123-137` returns the raw string.
  - `co_scientist/evidence/retrieval_support.py:205-210` uses a bare URL
    fallback.
  - `retrieval_support.py:288-307` uses the raw text as content.
  - `co_scientist/evidence/search_support.py:177-190` returns `[]`.
  - `co_scientist/agents/generation/literature_review/enrichment.py:57-62`
    returns a sentinel.
- **Difference:** behaviour.
  - Reproduced by the engine-science auditor: `parse_content_result("2024")`,
    `("[1,2]")` and `("null")` raise `AttributeError`.
  - The call at `co_scientist/research_adapter/__init__.py:305` sits
    outside any `try`.
- **Single version:** `platform/retrieval/results.py`, a
  `decode_tool_result` that returns a tagged result.
- **Lines saved (measured):** 56.
- **Risk:** each fallback is deliberate for its tool, so keep them as
  policies.
- **Belongs:** separate fix for the crash at `:305`, then phase 5.

#### B-03 Parsing tool-call `arguments` JSON: four variants

- **Implementations:**
  - `co_scientist/llm/tools/transcript.py:35-46` returns None.
  - `co_scientist/workspace/tools.py:347-357` raises a typed error.
  - `co_scientist/mcp_client/__init__.py:391` calls bare `json.loads`
    (uncaught).
  - `app/app/qa/manifest.py:394-402` falls back to `{"query": raw}`.
- **Difference:** behaviour on malformed arguments.
- **Single version:** `platform/llm/tool_args.py`.
- **Lines saved (measured):** 32.
- **Risk:** the Q&A fallback is intended UX (`qa/manifest.py:395`).
- **Belongs:** phase 5.

#### B-04 Coercing untyped model JSON into `list[str]`: eight variants that disagree on `[None, " a ", ""]`

- **Implementations:**
  - The canonical one, `co_scientist/llm/structured/validate.py:58-131`
    (`coerce_json_list`), is used only by the app.
  - The engine variants:
    - `co_scientist/research/serialization.py:174-177`
    - `co_scientist/research_adapter/__init__.py:191-194`
    - `co_scientist/agents/reflection/reflection.py:34-43`
    - `co_scientist/agents/reflection/review.py:105-111`
    - `co_scientist/agents/meta_review/meta_review.py:88-91`
    - `co_scientist/agents/generation/citations.py:14-24`
  - The app variants: `app/app/run_modes/__init__.py:103-106,283-284` and
    `app/app/qa/manifest.py:123-127`.
  - About 30 inline `isinstance(..., list)` guards in the engine agents.
- **Difference:** behaviour. On `[None, " a ", ""]`, the outputs include
  `["a"]`, `["None","a"]` (a literal "None" bullet reaches prompts) and
  `[" a ",""]`.
- **Single version:** `platform/llm/structured`, plus a
  `clean_str_list(dedupe, cap)` wrapper.
- **Lines saved (measured):** 33.
- **Risk:** some offline fixtures may encode `"None"`.
- **Belongs:** phase 5.

#### B-05 LLM wall-clock ceilings resolved in two places

- **Implementations:**
  - `co_scientist/llm/request/completion.py:24-25,110-142` reads
    `COSCIENTIST_LLM_TIMEOUT_SECONDS` and adds 30 s of grace.
  - `app/app/llm_request.py:20-32` uses a literal 600.0, ignores the
    environment variable, and adds no grace.
  - `app/app/goal_text.py:140-146` wraps a third `wait_for` around it.
- **Difference:** behaviour. An operator who changes the env var changes
  engine calls but not app chat calls. `engine/AGENTS.md:253` says the
  variable bounds "every completion".
- **Single version:** `platform/llm/`, as `resolve_timeout`.
- **Lines saved (measured):** 3.
- **Risk:** streams use silence deadlines, and that must stay
  (`docs/OPERATIONS.md:71`).
- **Belongs:** phase 5.

#### B-06 Environment reading: the same variable or kind of value parsed with different rules

- **Implementations:**
  - Boolean parsing:
    - `co_scientist/config/env_vars.py:35-40` accepts true, 1, yes and on.
    - `co_scientist/llm/admission/free_policy.py:215-219` is strict and
      raises.
    - `app/app/process_mode.py:36` accepts only `== "1"`.
    - `app/app/engine_adapter/opts.py:39` treats anything except `"0"` as
      on.
  - Skills paths: `co_scientist/skills/__init__.py:26-27,52,67` versus
    `co_scientist/sandbox/policy.py:122-136` (literal names, no `strip`,
    `expanduser`, no `is_dir` check).
  - Retention days: `app/app/retention.py:18-29` has its own int parser.
- **Difference:** behaviour.
  - `COSCIENTIST_FORCE_OFFLINE=true` does not force offline mode, but
    `COSCIENTIST_DEV_MODE=true` is honoured.
  - `FORCE_LITERATURE_REVIEW=false` leaves literature review on.
  - A skills path with a trailing space is ignored by the skills loader but
    allow-listed by the sandbox.
- **Single version:** `core/config.py`, with typed readers.
- **Lines saved (measured):** 15 (the sandbox re-read block).
- **Risk:** the free-model parser fails closed on purpose, so keep a strict
  mode.
- **Belongs:** separate fix for the skills-path split, then phase 5.

#### B-07 Formatting an article for a prompt: at least seven formatters

- **Implementations:**
  - `co_scientist/prompts/generation_draft.py:102-118`
  - `co_scientist/agents/generation/literature_review/synthesis.py:205-210`
  - `co_scientist/agents/reflection/deep_verification_evidence.py:66`
  - `co_scientist/evidence/relevance.py:70-72`
  - `co_scientist/agents/meta_review/research_overview_evidence.py:217-234`
  - `co_scientist/agents/generation/citations.py:93-95`
  - `co_scientist/prompts/literature.py:102-104,174`
  - Helpers that exist but are bypassed: `co_scientist/prompts/_common.py:184-189`.
  - The missing-title default is `"Unknown"` in some formatters and
    `"Untitled paper {n}"` in another.
- **Difference:** what the model sees. Citation labels are built two ways
  (`agents/generation/citations.py:64-66` and
  `app/app/report/markdown/hypothesis.py:36-41`).
- **Single version:** `science/`, as `render_article(article, style)`.
- **Lines saved (measured):** 66 in four counted ranges.
- **Risk:** prompts are hashed into verification fingerprints
  (`agents/reflection/deep_verification.py:105-115`), so changing a
  formatter invalidates them; bump the prompt version per style.
- **Belongs:** phase 5.

#### B-08 Model `to_dict` and `from_dict` with different rules for unknown keys

- **Implementations:**
  - Tolerant loaders: `co_scientist/models/__init__.py:51-57` (`Article`),
    `models/metrics.py:31-36`, `models/matchup.py:39-44`.
  - `co_scientist/scheduling/models.py:54-60` writes the same filter out
    again.
  - `co_scientist/config/schema.py:119,200,245,352`.
  - Strict loader: `models/__init__.py:316-352`. `Hypothesis.from_dict`
    calls `cls(**payload)`, and its `to_dict` lists keys by hand.
- **Difference:** behaviour. A checkpoint with an added field loads into
  most models but raises in `Hypothesis`. A new `Hypothesis` field that is
  missing from `to_dict` is silently not persisted.
- **Single version:** `core/types.py`, as a record mixin.
- **Lines saved (measured):** 6.
- **Risk:** strictness may be deliberate for append-only lineage.
- **Belongs:** phase 5.

#### B-09 Disposition, verdict and status vocabularies as bare string literals

- **Implementations:**
  - `viable` appears at 8 sites, `rejected` at 11 and `duplicate` at 11.
  - `duplicate` is defined four times: `app/app/engine_adapter/drain/hypotheses.py:243`
    and `:384`, `co_scientist/agents/reflection/owed_review.py:16`,
    `co_scientist/agents/reflection/review_gate.py:275`.
  - The `undermined` verdict is defined in the engine
    (`co_scientist/models/__init__.py:154`) and re-spelled at
    `app/app/elo.py:39` and `app/frontend/src/lib/hypotheses.ts:9`.
  - The withdrawn statuses are copied at `app/frontend/src/lib/hypotheses.ts:5`.
- **Difference:** cosmetic today, but likely to drift. `owed_review.py:14-16`
  mirrors an app value "without an engine-to-app import", so value
  ownership points the wrong way.
- **Single version:** `core/`, as str-valued `ReviewDisposition` and
  `HypothesisStatus` enums.
- **Lines saved (measured):** 8 (redundant constants and comments).
- **Risk:** the values are persisted in checkpoints and must not change.
- **Belongs:** phase 5.

#### B-10 Paper identity: DOI, PMID, URL and title normalized seven ways

- **Implementations:**
  - Engine:
    - `co_scientist/evidence/search_fusion.py:158-176` (title only,
      whitespace-sensitive)
    - `co_scientist/llm/tools/transcript.py:222-227`
    - `co_scientist/agents/reflection/deep_verification_evidence.py:173-196,264-286`
  - App:
    - `app/app/report/markdown/hypothesis.py:82-105`
    - `app/app/retraction_set.py:19-25` (the only one that strips doi.org
      prefixes)
    - `app/app/citations/__init__.py:179-180,192-194`
    - `app/app/engine_adapter/drain/hypotheses.py:35,51-58` (recovers the
      PMID from a URL)
  - MCP: `engine/mcp_server/tools/lit_review/opencitations.py:16,119-125`.
  - The URL prefix `https://doi.org/` is written inline in 5 files.
- **Difference:** behaviour.
  - One DOI can count as "retracted" under one spelling and "resolvable"
    under another.
  - `_resolve_doi` checks the normalized form but resolves the raw one.
  - A paper's URL depends on which tool retrieved it.
- **Single version:** `core/ids.py` (`normalize_doi`, `normalize_pmid`,
  `doi_url`, `pubmed_url`), plus a `pmid` field on `Article`. The MCP
  server keeps a small copy.
- **Lines saved (measured):** 70 in total: about 45 net in the engine and
  25 in the app.
- **Risk:** dedup keys decide which duplicate wins, and evidence ids are
  persisted.
- **Belongs:** phase 5.

#### B-11 Hypothesis query generation cloned between reflection and evolution

- **Implementations:**
  - `co_scientist/agents/reflection/review_evidence.py:176-216`
  - `co_scientist/agents/evolution/evolve_grounding.py:78-109`: same
    prompt, schema, temperature, error handling and an identical 3-line
    cleaner.
  - A third call shape with no cleaner:
    `co_scientist/agents/generation/literature_review/queries.py:94-110`.
- **Difference:** cosmetic today. The third copy skips whitespace cleaning.
- **Single version:** `science/retrieval/hypothesis_queries.py`.
- **Lines saved (measured):** 32.
- **Risk:** prompt names are telemetry keys, so keep them as parameters.
- **Belongs:** phase 5.

#### B-12 Supervisor-guidance prompt formatters: six copies of one guard, one of them robust

- **Implementations:**
  - The six formatters:
    - `co_scientist/prompts/review.py:189-203`
    - `co_scientist/prompts/generation_debate.py:50-75`
    - `co_scientist/prompts/generation_draft.py:70-87`
    - `co_scientist/prompts/planning.py:309-330`
    - `co_scientist/agents/evolution/evolve_prompt.py:363-380`
    - `co_scientist/prompts/ranking.py:236-247`
  - Evolution guidance is rendered twice (`planning.py:292-306`), and so
    are the config preferences (`prompts/review.py:138-158` and
    `generation_draft.py:38-60`).
- **Difference:** behaviour. Only `generation_draft.py:76-82` type-checks
  nested values. The others raise `AttributeError` if the model returns a
  string for `workflow_plan`.
- **Single version:** `science/prompts/guidance.py`. Normalize the types
  once, at the supervisor's output.
- **Lines saved (measured):** 36.
- **Risk:** prompt text must stay byte-identical.
- **Belongs:** phase 5. The normalizer alone is a small separate fix.

#### B-13 Fan-out and control-flow re-raise copied

- **Implementations:**
  - 32 `asyncio.gather` sites in the engine.
  - The block that re-raises control-flow errors is copied three times:
    `co_scientist/agents/reflection/review.py:365,375`,
    `co_scientist/agents/generation/literature_tools/validate.py:395-397,424-427`,
    `app/app/engine_tasks/ranking.py:161-162,193-195`.
  - Two gathers have no re-raise:
    `co_scientist/agents/generation/literature_review/orchestration.py:489-496`
    and `enrichment.py:212` (MCP-only today).
- **Difference:** latent. An LLM call added under those two gathers would
  swallow budget and rate-limit park errors.
- **Single version:** `orchestration/`, as `gather_isolated(coros, limit)`.
  Semaphores must be created per event loop.
- **Lines saved (measured):** 24.
- **Risk:** the AGENTS.md rule that no asyncio primitive may be shared
  across cohort event loops.
- **Belongs:** phase 5.

#### B-14 The "usable article" predicate and retraction filtering

- **Implementations:**
  - `co_scientist/agents/reflection/deep_verification_evidence.py:39-48`
    (`showable_articles`).
  - Six inline `used_in_analysis` filters, for example
    `co_scientist/agents/generation/citations.py:90` and
    `co_scientist/agents/meta_review/research_overview_evidence.py:29,201`.
  - `co_scientist/research_adapter/__init__.py:199` `_CARRIED_FIELDS`
    leaves out `is_retracted`.
- **Difference:** behaviour. Articles found by deep research bypass
  retraction flagging in the engine.
- **Single version:** `science/evidence/articles.py`, as `citable()`.
- **Lines saved (measured):** 14.
- **Risk:** retraction metadata for those articles needs plumbing first.
- **Belongs:** phase 5.

#### B-15 Review rubric axes, score bounds and the Elo K-factor copied into the app

- **Implementations:**
  - Axes: `co_scientist/schemas/review.py:276-285`,
    `co_scientist/agents/reflection/review_gate.py:213-222`,
    `app/app/engine_adapter/drain/reviews.py:158-167`.
  - Bounds: `schemas/review.py:288-289` and `drain/reviews.py:146-147`.
  - K = 24: `co_scientist/constants/__init__.py:122` and
    `app/app/config.py:90`.
- **Difference:** latent. The app comment says "tests pin it", but no test
  compares the app copy with the engine's `_SCORE_CRITERIA`. A ninth axis
  would be dropped silently.
- **Single version:** `core/`, as rubric constants.
- **Lines saved (measured):** 14.
- **Risk:** low.
- **Belongs:** phase 5. Add the pinning test now.

#### B-16 Per-run budgeted "issuance marker": same shape, three copies

- **Implementations:**
  - `co_scientist/agents/reflection/owed_review.py:19-43` (cap 24, `:12`)
  - `co_scientist/agents/reflection/review_gate.py:391-423` (cap 24, `:382`)
  - `co_scientist/agents/reflection/deep_verification.py:118-123`
- **Difference:** the eligibility rules differ; the marker, count and cap
  logic is identical.
- **Single version:** `science/` or `orchestration/`, as
  `IssuanceBudget(marker, cap, eligible)`.
- **Lines saved (measured):** 25 (one copy of the
  issued/mark/targets trio).
- **Risk:** markers are checkpointed (`docs/OPERATIONS.md:175-177`).
- **Belongs:** phase 5.

### App backend

#### B-17 Run tiers: names and tables in eight places across four packages

- **Implementations:**
  - App:
    - `app/app/run_modes/__init__.py:204-266`: `RUN_TIER_DEFAULTS` and a
      hand-written `RUN_TIER_PATTERN`
    - `app/app/api_contracts/common.py:10,21-23`: two Literals with the
      same values
    - `app/app/engine_adapter/opts.py:34`: the `deep` tier set
    - `app/app/free_usage.py:15`
  - Engine: `co_scientist/research_adapter/__init__.py:346-349,380-390`.
  - Evaluations: `evaluations/claim_support_eval.py:222`.
  - Frontend:
    - `app/frontend/src/workbench/run_spec.ts:12-15,92-117`
    - `app/frontend/src/workbench/pages/home_landing_content.ts:129-138`
      (tier sizes and `INITIAL_ELO`, kept in sync by a code comment only)
    - `app/frontend/src/api/system.ts:44`
- **Difference:** latent. All copies agree today. A new tier needs 8 edits,
  and no test pins the engine tables or the landing numbers to
  `RUN_TIER_DEFAULTS`.
- **Single version:** `core/`, as a `RunTier` enum with a `TierPolicy`
  table, served to the frontend.
- **Lines saved (measured):** 12 in the backend. The frontend tables (13
  and 26 lines) would be generated rather than deleted.
- **Risk:** tier names and sizes are persisted in run configs.
- **Belongs:** phase 5, plus frontend lane Part 1 for the guard test.

#### B-18 Pipeline stage and node vocabulary hand-listed six times

- **Implementations:**
  - The engine source of truth: `co_scientist/agents/__init__.py:29-57`
    (`NODE_REGISTRY`).
  - App:
    - `app/app/engine_adapter/events.py:17-31`, whose comment claims the
      list is derived from the engine but which is a literal list
    - `app/app/store/runs_views.py:172-183`
  - Frontend:
    - `app/frontend/src/workbench/pages/chat_home_stage.tsx:681-714`
    - `workbench/pages/run_detail_data.ts:157-173`
    - `workbench/pages/run_detail_activity_log.tsx:295-342`
- **Difference:** latent. Only the activity vocabulary is test-guarded
  (`app/tests/test_architecture.py:220`). A new node renders as "other" or
  null in up to 3 frontend tables.
- **Single version:** derive from `NODE_REGISTRY` in `orchestration/`, and
  generate a `wire_stages.ts`.
- **Lines saved (measured):** 63.
- **Risk:** the event-type spellings are persisted. The home-phase mapping
  is UX data, so keep the table and derive only its keys.
- **Belongs:** phase 5, plus frontend lane Part 1.

#### B-19 A hypothesis's display title and statement resolved four ways

- **Implementations:**
  - `app/app/text_utils.py:18-27` (140 characters)
  - `app/app/qa/snapshot.py:63-64` (160 characters)
  - `app/app/qa/manifest.py:356` (`"Untitled"`)
  - `app/app/qa/__init__.py:234` (`"Untitled hypothesis"`)
  - The persisted cap is 120 characters
    (`app/app/engine_adapter/drain/hypotheses.py:398-409`).
- **Difference:** behaviour. A hypothesis with no title shows different
  text in the report and in Q&A.
- **Single version:** a `HypothesisView` in `domains/research_state/`.
- **Lines saved (measured):** 6.
- **Risk:** low.
- **Belongs:** phase 5.

#### B-20 One app chat-completion wrapper written four times

- **Implementations:**
  - Four request-and-stream wrappers:
    - `app/app/interviews/model.py:476-558`
    - `app/app/run_start_announcement.py:33-111`
    - `app/app/qa/__init__.py:38-92`
    - `app/app/goal_text.py:121-195`
  - The same stall and total constants appear verbatim in three of them
    (`interviews/model.py:476-477`, `run_start_announcement.py:33-34`,
    `qa/__init__.py:39-40`).
  - The thinking-kwargs choice is repeated three times.
  - There are three reasoning-detection methods (see A-08).
- **Difference:** the request, delta reading and constants match; the
  reasoning detector differs.
- **Single version:** `platform/llm/`, as `stream_chat`.
- **Lines saved (measured):** 23. These are the constant pairs (4 lines)
  and the delta readers (19 lines); the retry blocks are counted under
  A-08.
- **Risk:** the streaming sinks differ per surface (documented,
  `docs/OPERATIONS.md:71`).
- **Belongs:** phase 5.

#### B-21 The "active run status" set defined six times

- **Implementations:**
  - `app/app/store/runs_views.py:19-23`, imported by its private name from
    `store/runs.py:13` and `engine_tasks/ranking.py:28`.
  - `app/app/store/tasks_lifecycle.py:196`.
  - `app/app/runs/crud.py:406,607-611`.
  - `app/app/runs/lifecycle.py:233-237,410-414`.
- **Difference:** none today. Some copies use enum values and some use
  strings.
- **Single version:** `ACTIVE_STATUSES` next to `RunStatus`.
- **Lines saved (measured):** 17.
- **Risk:** low. Keep safety's wider 5-state set separate.
- **Belongs:** phase 5.

#### B-22 Model fallback chain for semantic safety and the claim verifier written twice each

- **Implementations:**
  - `app/app/safety/__init__.py:333-338,369-374`
  - `app/app/engine_tasks/gate.py:299-304`
  - `app/app/engine_adapter/drain/final_state.py:155-160`
  - `app/app/execution_policy.py:19-25` reads the raw fields without the
    fallback.
- **Difference:** latent. `execution_policy` would disagree about which
  models are "free" if the chain changed.
- **Single version:** `Settings.effective_semantic_safety_model` and
  `effective_claim_verifier_model`.
- **Lines saved (measured):** 16.
- **Risk:** low. Keep the two different failure returns.
- **Belongs:** phase 5.

#### B-23 Safety terminal-status mapping (block to BLOCKED, hold to PAUSED) built twice

- **Implementations:** `app/app/safety/__init__.py:136-151` and `:154-217`.
- **Difference:** the payloads are duplicated as literals. The guards
  differ on purpose.
- **Single version:** `domains/safety/gate_status.py`.
- **Lines saved (measured):** 16.
- **Risk:** event ordering inside one transaction is part of the stream
  contract.
- **Belongs:** phase 5.

#### B-24 JSON column decoding hand-rolled in about eight places, strict in some and tolerant in others

- **Implementations:**
  - The shared helper `app/app/store/db.py:142-159` (`_list_by_run`).
  - Hand-rolled strict decoders: `store/interviews.py:74,88,123`,
    `store/models.py:116,204-219`, `store/checkpoints.py:82`,
    `store/reports.py:92`.
  - Hand-rolled tolerant decoders: `store/models.py:129-137` and
    `store/hypotheses.py:214-225`.
  - The event-row mapping is copied twice (`store/events.py:249-257` and
    `:275-282`).
- **Difference:** behaviour on malformed JSON varies by table. A corrupt
  `meta_json` degrades quietly, while a corrupt `config_json` fails the
  read.
- **Single version:** `platform/db/rows.py`, as
  `json_col(row, name, default, strict=)`.
- **Lines saved (measured):** 33.
- **Risk:** keep each reader's strictness. Column names are persisted.
- **Belongs:** phase 5.

#### B-25 Parsing BYOK request headers copied three times, with different follow-up checks

- **Implementations:** `app/app/runs/crud.py:46-66`,
  `app/app/runs/chat.py:148-154`, `app/app/interviews/turns.py:42-51`.
- **Difference:** only run creation validates the key live. No document
  says why chat and interview skip that.
- **Single version:** `domains/access/byok.py`.
- **Lines saved (measured):** 17.
- **Risk:** low.
- **Belongs:** phase 5.

#### B-26 Ownership checks written in four styles

- **Implementations:**
  - The middleware, which parses the path itself: `app/app/main.py:240-263`.
  - `app/app/interviews/turns.py:31-39`.
  - `app/app/runs/crud.py:73-82`, which relies on an earlier
    `require_client_scope`.
  - `app/app/qa/snapshot.py:123`.
  - SQL filters: `store/documents.py:66,85,156` and `logs_api.py:180-187`.
  - The 404 "run not found" is raised inline at 7 sites.
- **Difference:** the rule "an empty identity owns nothing" is
  re-implemented per site, and two sites depend on an earlier check.
- **Single version:** `domains/access/ownership.py` and `api/errors.py`.
- **Lines saved (measured):** 25.
- **Risk:** keep the convention of 404 instead of 403, and the middleware
  order.
- **Belongs:** phase 5.

#### B-27 Document size caps and excerpts differ by entry point

- **Implementations:**
  - Caps:
    - `app/app/runs/models.py:99,112`: 200,000 characters.
    - `app/app/document_ingest.py:27,91,105`: 25 MB with no character cap
      on extracted text.
  - Excerpts:
    - `store/documents.py:12,145-149`: 4,000 characters with a truncation
      marker.
    - `run_corpus.py:77-78,97`: 6,000 characters, cut silently.
  - The upload handler is copied: `documents.py:54-59` and
    `runs/contrib.py:111-115`.
- **Difference:** behaviour.
- **Single version:** `domains/documents/ingest.py`.
- **Lines saved (measured):** 14.
- **Risk:** existing runs keep their old sizes, so enforce at ingest only.
- **Belongs:** separate fix for the cap mismatch, then phase 5.

#### B-28 Lease-liveness predicates written in Python at five sites

- **Implementations:**
  - `app/app/store/runs.py:18-27`, which checks expiry.
  - `app/app/engine_tasks/support.py:344-367`, which does not check expiry.
  - `app/app/task_worker/enqueue.py:106-113,152-158,293-296`.
  - The SQL versions in `store/tasks_lifecycle.py`.
- **Difference:** expiry is enforced in some places and not in others. No
  reason is documented.
- **Single version:** `orchestration/leases.py`.
- **Lines saved (measured):** 12.
- **Risk:** high, because leases are an operational invariant. Write down
  which sites must check expiry first.
- **Belongs:** phase 5, carefully.

#### B-29 Subprocess confinement: the engine sandbox versus the app's document parsing

- **Implementations:**
  - `co_scientist/sandbox/runner.py:144-151,216-224`: landlock, seccomp,
    cgroups.
  - `app/app/document_ingest.py:176-185` with `app/app/pdf_worker.py:10-12`:
    rlimits only.
  - `document_ingest.py:369-378` (tesseract): a timeout only.
- **Difference:** behaviour. User-supplied PDFs get rlimits but no
  filesystem or network confinement, and no document explains the split.
- **Single version:** a document-parsing profile in `platform/sandbox`.
- **Lines saved (measured):** 35 lines of ad-hoc process management would
  be replaced.
- **Risk:** it must keep working where landlock and cgroups are
  unavailable (Railway).
- **Belongs:** phase 5. This is a security-hardening note.

### MCP server

#### B-30 SSRF and URL guard: two near-clones plus a third layer of the same checks

- **Implementations:**
  - `app/app/pinned_http.py:10-82`: sync, with a fallback from HEAD to GET.
  - `engine/mcp_server/safe_http.py:10-74`: async.
  - `engine/mcp_server/tools/web_fetch.py:15-51` repeats the scheme, host
    and metadata checks before calling `validate_http_url`.
  - The metadata-host set is written three times (`pinned_http.py:44`,
    `safe_http.py:48`, `web_fetch.py:19`).
  - The tests mirror each other: `app/tests/test_pinned_http.py` and
    `engine/mcp_server/tests/test_safe_http.py`.
- **Difference:** drift has started. When `getaddrinfo` returns no
  addresses, the two copies raise different messages
  (`safe_http.py:25-26` against `pinned_http.py:24-25`). A fix to one copy,
  such as a new metadata host, will not reach the other.
- **Single version:** `platform/retrieval/safe_http.py` for the app. The
  MCP server keeps its copy (it cannot depend on the engine), plus one
  contract test both suites run.
- **Lines saved (measured):** 78 in all: 57 lines identical between the
  two copies, plus 21 redundant pre-check lines in `web_fetch.py`.
- **Risk:** this is a security boundary. DNS pinning and SNI must not
  change.
- **Belongs:** phase 5. The `web_fetch.py` cleanup is a small separate fix.

#### B-31 Paper record shapes: different keys per MCP source, and two engine normalizers

- **Implementations:**
  - MCP builders: `pubmed_client.py:145-162`, `search_pubmed.py:65-84`,
    `europepmc_search.py:47-71`, `openalex_search.py:77-110`,
    `arxiv_search.py:54-72`, `web_providers.py:142-172`.
  - Engine normalizers: `co_scientist/evidence/search_support.py:164-175`
    and `co_scientist/tools/response_parser.py` (305 lines, one caller at
    `agents/generation/literature_tools/validate.py:46,130`).
- **Difference:** behaviour.
  - Europe PMC's `journal` field is dropped, because
    `article_support.py:89` reads only `publication or venue`.
  - Europe PMC authors are a string, not a list.
  - `ResponseParser` drops `doi`, `pmid` and `is_retracted`.
  - `search_support.py:119-120` falls back to an `arxiv_id` key that no
    tool emits.
- **Single version:** one `PaperRecord` in the MCP server, and one engine
  normalizer in `platform/retrieval/`.
- **Lines saved (measured):** up to 305, by retiring `response_parser.py`.
- **Risk:** the field-mapping DSL in `tools.yaml` can be overridden by
  users.
- **Belongs:** phase 5.

#### B-32 MCP HTTP client policy decided per tool, at 12 places that construct a client

- **Implementations:**
  - `web_providers.py:188,211`, `web_fetch.py:165-167`.
  - `biomedical_databases.py:22,301,435,506,656-661`.
  - `opencitations.py:143-148`, `arxiv_search.py:104`,
    `europepmc_search.py:79`, `openalex_search.py:152`.
- **Difference:** behaviour.
  - `trust_env=False` is set on 3 of the 12, so behind an egress proxy 3
    tools bypass it and 9 use it.
  - A user agent is set once.
  - Timeouts are 10, 15, 30 or 45 seconds with no stated reason.
- **Single version:** `mcp_server/http.py`, as `make_client`.
- **Lines saved (measured):** 24 at construction sites, about 0 net. The
  gain is one policy.
- **Risk:** proxy behaviour changes where a proxy is required.
- **Belongs:** phase 5.

#### B-33 Request pacing: two pacers in MCP, and the app calls NCBI unpaced

- **Implementations:**
  - `engine/mcp_server/entrez.py:77-108`: a sync pacer.
  - `engine/mcp_server/tools/_pacing.py:6-21`: an async pacer.
  - `app/app/citations/__init__.py:173,192-206`: 6 parallel PMID lookups
    with no key or pacing, which map HTTP 429 to "not found".
- **Difference:** behaviour. Throttling becomes "unresolvable citation".
- **Single version:** one `RequestPacer`. The app should route PMID checks
  through MCP or share the NCBI settings.
- **Lines saved (measured):** about 20.
- **Risk:** the tests inject a clock and a sleep function, and those seams
  must stay.
- **Belongs:** phase 5. Treating 429 as "not found" is a separate fix.

#### B-34 HTML cleaning: three helpers, and two sources left uncleaned

- **Implementations:**
  - `engine/mcp_server/text_extraction.py:12-33` (`clean_markup`)
  - `tools/web_providers.py:14-24` (`clean_snippet`)
  - `tools/lit_review/arxiv_search.py:28-29` (whitespace only)
  - The `\s+` regex is defined three times.
  - OpenAlex titles and abstracts (`openalex_search.py:98,101`) get no
    cleaning at all.
- **Difference:** behaviour. `<p>a</p>b` becomes "a b" in one helper and
  "ab" in the other. The unescape order differs on purpose; see
  [Intentional differences](#intentional-differences).
- **Single version:** `text_extraction.py`, as `clean_markup(escaped=)`.
- **Lines saved (measured):** 16.
- **Risk:** the cleaned text feeds token-overlap scores.
- **Belongs:** phase 5.

#### B-35 MCP configuration surface: three cache-directory defaults and scattered environment reads

- **Implementations:**
  - Cache directory:
    - code default `./cache/literature_review`
      (`tools/lit_review/search_pubmed.py:207`)
    - `engine/mcp_server/.env.example:10` (`./paper_cache`)
    - the compose files mount `mcp_server/paper_cache`
      (`engine/docker-compose.yml:13`, `app/docker-compose.yml:66`)
  - 15 environment reads in 7 files.
  - Nothing tests that the MCP tool registry (`server.py:96-125`) matches
    `tools.yaml`.
- **Difference:** behaviour, by reading. The compose cache mount is never
  written, so the PubMed cache is lost when the container is recreated.
- **Single version:** `mcp_server/settings.py`, plus a parity test.
- **Lines saved (measured):** 0. The value is a correct path.
- **Risk:** moving the directory orphans local caches.
- **Belongs:** separate fix (the compose path), then phase 5.

### Build and config

#### B-36 Container definitions repeated with weaker variants

- **Implementations:**
  - `engine/docker-compose.yml:16` has a healthcheck with no
    `raise_for_status`, so it reports healthy on an HTTP 500. The app
    compose file checks status (`app/docker-compose.yml:77`).
  - `engine/docker/sandbox-linux.Dockerfile:3` uses an unpinned
    `python:3.12-slim`. The four production Dockerfiles pin a digest, as
    `docs/DEPLOYMENT.md:26` requires.
  - `app/docker/entrypoint.sh:25` hard-codes port 8008.
- **Difference:** behaviour in local compose only.
- **Single version:** one healthcheck snippet, and the digest in one build
  argument.
- **Lines saved (measured):** 20 (the duplicated MCP compose service).
- **Risk:** low.
- **Belongs:** separate fix (healthcheck and digest).

#### B-37 The default model id written in eight places

- **Implementations:**
  - The declared default: `app/app/config.py:16`.
  - The model profile: `co_scientist/llm/profile/__init__.py:149`.
  - Restated in `app/app/byok_models.py:23`, `.env.example:11`,
    `app/.env.example:2,12-14` and `.github/workflows/benchmark.yml:28`.
- **Difference:** latent. `make setup` copies `.env.example` into `.env`,
  which then overrides `config.py`.
- **Single version:** `app/app/config.py` only. Leave the example lines
  commented out.
- **Lines saved (measured):** 5.
- **Risk:** someone may rely on the seeded `.env`.
- **Belongs:** separate fix.

#### B-38 Toolchain version pins repeated, and two pairs disagree

- **Implementations:**
  - `actions/setup-python` is v7.0.0 in `.github/workflows/ci.yml:163,221,321,363,434`
    but v6.3.0 in `.github/actions/setup-backend/action.yml:9`.
  - uv is 0.11.32 in CI but 0.12.19 in `requirements/README.md`.
  - The ruff pin appears three times (`ci.yml:168`, `engine/pyproject.toml:42`,
    `app/pyproject.toml:36`).
  - CI runs Node 24, so it never tests the declared 22.13 floor.
- **Difference:** two pairs disagree today.
- **Single version:** composite actions and one tool-versions file.
- **Lines saved (measured):** 58 lines of repeated CI YAML.
- **Risk:** composite actions cannot take SHA pins from a variable.
- **Belongs:** separate fix for the two disagreements, then low priority.

#### B-39 Install, test and lint commands repeated per consumer

- **Implementations:**
  - MCP install: `Makefile:173,212`, `ci.yml:331`, `benchmark.yml:48-50`.
  - The dev extra lacks `mypy` and `types-defusedxml`, so two places add
    them by hand.
  - Format-check scope: `Makefile:252` checks `.` but `ci.yml:177` checks
    `app tests`.
- **Difference:** a file in `app/` outside those two directories passes CI
  but fails `make lint`.
- **Single version:** have CI call the make targets.
- **Lines saved (measured):** 25.
- **Risk:** CI uses uv and the Makefile uses pip.
- **Belongs:** phase 5 (tooling).

### Frontend

#### B-40 Buttons: no shared component (the calibration finding)

- **Implementations:** 50 `<button>` elements in 23 files with 45 distinct
  class expressions (see [Calibration](#calibration)). The same "primary"
  role has four recipes:
  - `app/frontend/src/workbench/classes.ts:48`
  - `workbench/pages/chat_timeline_bubble.tsx:219-232`
  - `components/error_boundary.tsx:66`
  - `workbench/pages/home_landing.tsx:80-84`

  Disabled styling appears on 11 of the 50.
- **Difference:** cosmetic, plus accessibility (see B-49).
- **Single version:** `src/shared/ui/button.tsx`, with variants and sizes
  and the focus ring and disabled state built in.
- **Lines saved (measured):** 172 (114 class-bearing tag lines and 58 lines
  of class constants).
- **Risk:** the global button transition is unlayered (`index.css:396`),
  and three buttons depend on that ordering.
- **Belongs:** frontend lane Part 1.

#### B-41 Icon-only buttons: six sizes, three radii and four hover colours

- **Implementations:** a ghost icon button repeated at
  `chat_questions.tsx:237-241`, `chat_timeline_message_actions.tsx:43-48`,
  `chat_timeline_run_spec_card.tsx:169-173`, `chat_timeline_run_spec_editor.tsx:78-80`
  and `markdown_message_renderer.tsx:159-161`. Further variants appear in
  `chat_composer.tsx:136,344,510`, `settings_dialog.tsx:103` and
  `chat_workspace.tsx:517`.
- **Difference:** 7 icon buttons have only an `aria-label`, so mouse users
  get no hint.
- **Single version:** `src/shared/ui/icon_button.tsx`, which requires a
  label and derives the tooltip from it.
- **Lines saved (measured):** 5. Most of the saving is counted in B-40.
- **Risk:** composer CSS hooks.
- **Belongs:** frontend lane Part 1.

#### B-42 Text fields: three styles, already drifting

- **Implementations:**
  - `workbench/classes.ts:36`
  - `chat_questions.tsx:344-345` and `chat_timeline_run_spec_editor.tsx:71-73,156-158`,
    whose text colour and focus rule already differ
  - `chat_timeline_run_spec_card.tsx:555-559`, which has no focus style
- **Difference:** cosmetic, plus one missing focus indicator.
- **Single version:** `src/shared/ui/field.tsx`.
- **Lines saved (measured):** 4.
- **Risk:** touch devices need a font size of at least 16 px.
- **Belongs:** frontend lane Part 1.

#### B-43 Dialogs are assembled by hand twice, and the mobile drawer is not modal

- **Implementations:**
  - The primitives exist once, in `workbench/hooks/dom.ts:174-327`.
  - They are wired by hand in `feedback_dialog.tsx:78-89,118-133` and
    `settings_dialog.tsx:53-58,134-157`.
  - The drawer (`layout.tsx:122-137,333-342`) has only Escape and a scrim.
- **Difference:** behaviour. The drawer has no focus trap, no inert
  background and no `aria-modal`, which falls short of `app/AGENTS.md:156`.
- **Single version:** `src/shared/ui/dialog.tsx`.
- **Lines saved (measured):** 43.
- **Risk:** Escape handling must be stack-aware.
- **Belongs:** frontend lane Part 1.

#### B-44 Empty, loading and error states: eight error recipes and four reds

- **Implementations:**
  - Error states:
    - `run_detail_shell.tsx:156-166,226-238`
    - `chat_workspace.tsx:415-425`
    - `chat_timeline_run_spec_card.tsx:474-480`
    - `chat_timeline_run_spec_editor.tsx:190`
    - `error_boundary.tsx:37-41`
  - Loading states: `workbench_app.tsx:18-24`, `run_detail_shell.tsx:290-302`,
    `chat_home_stage.tsx:764`.
- **Difference:** cosmetic. `cosci-danger` (#b3261e) and `th-destructive`
  (#ba1a1a) are near-misses of the same red.
- **Single version:** `src/shared/ui/states.tsx`.
- **Lines saved (measured):** 8 (inline `style` blocks).
- **Risk:** tests assert the `role` attributes.
- **Belongs:** frontend lane Part 1.

#### B-45 Hover rules split between `hover:` and `[&:hover]:`

- **Implementations:** `hover:` 41 times and `[&:hover]:` 22 times, the
  latter concentrated in `layout_nav_rail.tsx` and `settings_dialog.tsx`.
- **Difference:** behaviour on touch devices. Only `hover:` is gated on
  `(hover:hover)`, so the other form leaves a sticky hover after a tap. No
  document gives a reason.
- **Single version:** the shared components, or one custom variant.
- **Lines saved (measured):** 0.
- **Risk:** changes the touch UX.
- **Belongs:** frontend lane Part 1.

#### B-46 Colour tokens: three palettes, 48 extra aliases, and invariant breaches

- **Implementations:**
  - The palettes:
    - `th-*` (`index.css:43-95`)
    - `cosci-*` (116 variables in `styles/tokens.css`)
    - the landing page's undocumented `--l-*` (`styles/home_landing.css:146-189`,
      28 hex declarations)
  - 93 bridge aliases point at 45 targets.
  - Arbitrary token references bypass existing utilities at
    `run_detail_shell.tsx:296-298` and `chat_home_stage.tsx:58,70,525`.
- **Difference:** cosmetic, with a high drift risk.
- **Single version:** `styles/tokens.css`.
- **Lines saved (measured):** 28.
- **Risk:** the landing page shows brand colours on purpose.
- **Belongs:** frontend lane Part 1.

#### B-47 Breakpoints: no tokens, and the phone breakpoint written four ways

- **Implementations:**
  - Inline arbitrary media variants: `[@media(max-width:700px)]` 144 times,
    plus 52 others.
  - `max-[700px]:` 53 times and `min-[701px]:` 58 times.
  - CSS `@media (max-width: 700px)` 4 times.
  - In JavaScript: `MOBILE_MEDIA_QUERY` (`workbench/hooks/dom.ts:6`).
  - 9 distinct width breakpoints in all.
- **Difference:** latent. The JS constant must stay equal to about 200
  utility uses.
- **Single version:** `--breakpoint-*` in `@theme`, and one JS constant.
- **Lines saved (measured):** 0.
- **Risk:** media-query ordering, and the e2e viewport sizes.
- **Belongs:** frontend lane Part 1.

#### B-48 Tabs and segmented controls: eight groups, none with tab semantics

- **Implementations:**
  - `run_detail_shell.tsx:95-150`
  - `layout_session_switch.tsx:62-96`, which re-implements the sliding pill
  - `settings_dialog.tsx:196-226,341-350`
  - `home_landing.tsx:372-405,1032-1060`
  - `home_landing_diagram.tsx:278-281`
  - `ideas_tab.tsx:255-258`
- **Difference:** accessibility. `aria-current="true"` and `"page"` are
  mixed, and there is no arrow-key navigation.
- **Single version:** `src/shared/ui/segmented.tsx`.
- **Lines saved (measured):** 12.
- **Risk:** the report tabs are route links.
- **Belongs:** frontend lane Part 1.

#### B-49 Focus rings: 25 variants, and 15 buttons with no project focus style

- **Implementations:** 80 `focus-visible:` uses with 25 distinct tails. Most
  controls show focus with a background tint only. `outline-none` appears 6
  times.
- **Difference:** accessibility. Of 50 buttons, 10 get a visible ring, about
  25 a tint, and about 15 nothing project-owned.
- **Single version:** a global `:focus-visible` rule plus the shared
  components.
- **Lines saved (measured):** 0.
- **Risk:** clashes with the MD3 state layers.
- **Belongs:** frontend lane Part 1.

#### B-50 Route paths built as about 14 string literals

- **Implementations:**
  - `tabPath` exists (`workbench/run_tabs.ts:24-26`) but is bypassed at
    `chat_home_stage.tsx:591` and `chat_workspace_timeline.tsx:364`.
  - `/chats/${id}` is built in 5 places.
  - Three functions decide which side of a session to open
    (`chat_home_stage.tsx:586-592`, `layout_nav_rail.tsx:445-452`,
    `layout_session_switch.tsx:96-100`).
  - The path is parsed by hand in `layout.tsx:81-85` and
    `feedback_dialog.tsx:40-41`.
- **Difference:** latent.
- **Single version:** `src/shared/lib/routes.ts`.
- **Lines saved (measured):** 19.
- **Risk:** the three side-decisions differ, so parameterize rather than
  pick one.
- **Belongs:** frontend lane Part 1.

#### B-51 A run's display title derived five ways

- **Implementations:**
  - `workbench/pages/run_detail_data.ts:89-92`
  - `workbench/hooks/use_chat_rehydrate.ts:90-93`
  - `workbench/layout_nav_rail.tsx:478-480`
  - `workbench/pages/chat_home_stage.tsx:598-602`, which does not trim the
    title
  - `chat_workspace.tsx:160-163`
- **Difference:** behaviour. The same run shows three different titles, and
  a whitespace-only title renders blank on the home card.
- **Single version:** `src/shared/lib/titles.ts`.
- **Lines saved (measured):** 14.
- **Risk:** the header deliberately shows more text.
- **Belongs:** frontend lane Part 1. The missing trim is a one-line separate
  fix.

#### B-52 `matchMedia` hooks: five implementations

- **Implementations:**
  - `workbench/hooks/dom.ts:5-41`
  - `workbench/pages/home_landing_hooks.tsx:7-26`
  - `workbench/theme_context.tsx:34-64`, the only one with the legacy
    Safari fallback
  - `chat_timeline_bubble.tsx:343-349`
  - `chat_home_stage.tsx:109-111`
- **Difference:** the feature test is written three ways.
- **Single version:** `src/shared/hooks/use_media_query.ts`.
- **Lines saved (measured):** 79.
- **Risk:** the lazy initial state and the defaults differ.
- **Belongs:** frontend lane Part 1.

#### B-53 Extracting a message from a caught error: one shared helper with one caller, and five inline copies

- **Implementations:**
  - The helper: `lib/text.ts:3-5`.
  - Inline copies: `run_detail_data.ts:237`, `chat_session_start_run.ts:185,779-785`,
    `chat_timeline_run_spec_editor.tsx:259`, `chat_session_handlers.ts:246-249,280-283`.
  - `readSseFrames` throws a plain `Error`, not `HttpError`
    (`api/runs.ts:622`).
- **Difference:** streamed endpoints lose the HTTP status.
- **Single version:** `src/shared/lib/errors.ts`.
- **Lines saved (measured):** 13.
- **Risk:** the fallback strings are user-facing copy.
- **Belongs:** frontend lane Part 1.

#### B-54 Client telemetry: three entry paths and two event dispatchers

- **Implementations:**
  - `lib/ui_logging.ts:7-10`
  - The event bus: `chat_session_transcript.ts:162-181` and
    `api/runs.ts:571-579`.
  - `layout_diagnostics.tsx:264-295`.
  - `api/runs.ts:14` imports from `workbench/`.
- **Difference:** behaviour. Event-bus records are dropped while the header
  diagnostics control is not mounted. `app/AGENTS.md:114` disagrees with
  `main.tsx:18-19`.
- **Single version:** `src/shared/telemetry/log.ts`.
- **Lines saved (measured):** 19.
- **Risk:** keep the recursion guard (`api/runs.ts:570`).
- **Belongs:** frontend lane Part 1.

#### B-55 Duration, relative-time and clock formatting

- **Implementations:**
  - `lib/text.ts:105-122` (`formatDurationPhrase`) and its callers
    `run_detail_active.tsx:19-22`, `chat_home_stage.tsx:669-679` and
    `run_detail_overview.tsx:357-363`.
  - `run_detail_activity_log.tsx:391-400` (`relativeTime`, which has no
    hours branch).
  - `layout_diagnostics_data.ts:38-46,163` and `chat_home_stage.tsx:659-667`.
  - "Now in seconds" is computed by hand 9 times.
- **Difference:** behaviour. The same page shows "2 hours" and "125m ago".
- **Single version:** `src/shared/lib/time.ts`.
- **Lines saved (measured):** 20.
- **Risk:** tests assert the exact strings.
- **Belongs:** frontend lane Part 1.

#### B-56 Hand-written TypeScript types mirror backend models outside the generated wire files, and have drifted

- **Implementations:**
  - `app/frontend/src/api/system.ts:3-52`, against
    `app/app/diagnostics_api.py:43-120` and `app/app/free_usage.py:100-113`.
  - `api/logs.ts:5-27`, `api/feedback.ts:3-10`, `api/runs.ts:98-105`.
  - `hooks/use_run_stream.ts:9-14`.
  - `lib/client_id.ts:31-46`.
- **Difference:** drift is visible.
  - `byok_enabled` and `enabled_tools` are missing from the frontend type.
  - Five operator-only fields are typed non-null, but the backend returns
    null for them to other callers.
- **Single version:** extend the `app/app/api_contracts/` generator.
- **Lines saved (measured):** 87 hand-kept type lines would be generated.
- **Risk:** needs backend contract work.
- **Belongs:** frontend lane Part 1, with phase 5 for the generator.

#### B-57 Polling and timers: one tick per card, no pause for hidden tabs, a fixed reconnect delay

- **Implementations:**
  - `workbench/hooks/history_context.tsx:84-96` (every 10 s)
  - `workbench/hooks/system_status_context.tsx:34` (every 60 s)
  - `workbench/hooks/timers.ts:3-11` `useNowTick`, created per card at
    `chat_home_stage.tsx:557-558`, even for finished runs
  - `hooks/use_run_stream.ts:112-117` (2 s fixed)
- **Difference:** background tabs keep polling `/status`, which runs probes.
  Only the diagnostics code follows the rule "never on a timer".
- **Single version:** `src/shared/hooks/use_poll.ts`.
- **Lines saved (measured):** 19.
- **Risk:** tests use fake timers.
- **Belongs:** separate fix (the per-card tick and the hidden-tab pause),
  then frontend lane Part 1.

### Tests

#### B-58 Scripted fake completion backends: three scripting variants with different exhaustion rules

- **Implementations:**
  - `engine/tests/_llm_fake.py:99-119` (`scripted_backend`)
  - `_llm_fake.py:250-262` (`patch_acompletion`, which does not raise)
  - `_llm_fake.py:381-388` (`Driver.provider`, which repeats the last item)
  - Inline fakes: about 25 in engine tests, and 43
    `install_completion_backend` calls in app tests
- **Difference:** they disagree on raising exceptions, on what happens
  after the script ends, and on whether kwargs are snapshotted.
- **Single version:** one `scripted_backend(repeat_last, snapshot)`.
- **Lines saved (measured):** 21.
- **Risk:** 33 call sites read the returned dict.
- **Belongs:** phase 5.

#### B-59 Two schema-filling fake LLMs that have drifted

- **Implementations:** the production `co_scientist/offline/llm.py:609-647`
  against the test fake `engine/tests/_llm_fake.py:166-182`, which imports
  six private names.
- **Difference:** behaviour. The fake omits the `scalar_values` and
  `optional_fields` hints (`offline/llm.py:626-627`), so engine pipeline
  tests get reviews shaped differently from the app's offline runs.
- **Single version:** production `offline_acompletion(leaf_factory=)`.
- **Lines saved (measured):** 25.
- **Risk:** tests assert on `stub-N` strings.
- **Belongs:** phase 5.

#### B-60 Completion and stream-chunk builders: six stream builders and three response shapes

- **Implementations:**
  - Stream builders: `app/tests/_client.py:117-147`,
    `_interviews_helpers.py:156-170`, `test_interviews.py:272-283`,
    `test_question_answering.py:24-37`, `test_qa_ideas.py:23-45`,
    `test_byok_flow.py:215-235`.
  - Response builders: `engine/tests/_llm_fake.py:217-247` and
    `offline/llm.py:574-577`.
- **Difference:** fidelity.
  - The default fake never reports usage.
  - `test_byok_flow.py:217` sets `delta.reasoning`, but production reads
    `reasoning_content`.
- **Single version:** one typed builder module.
- **Lines saved (measured):** 127.
- **Risk:** keep a minimal-shape builder for the fallback tests.
- **Belongs:** phase 5.

#### B-61 `make_tool_call` defined twice with swapped argument order

- **Implementations:** `engine/tests/_llm_fake.py:246` takes
  `(call_id, name, arguments)`; `engine/tests/_mcp.py:98` takes
  `(name, arguments, call_id)`. There is an inline copy at
  `test_workspace.py:157-163`.
- **Difference:** a wrong import raises no error, because all the arguments
  are strings.
- **Single version:** keep only the `_llm_fake.py` one.
- **Lines saved (measured):** 13.
- **Risk:** none.
- **Belongs:** separate fix.

#### B-62 The engine test fake is loaded by file path, by two other projects

- **Implementations:** `app/tests/_llm_fake_backend.py:11-28` (re-executes
  544 lines on each of 43 calls) and `evaluations/tests/_engine_fake_backend.py:12-23`.
  `isolate_offline_router` lives in `engine/tests/_mcp.py:105-109`, not
  where `engine/AGENTS.md:253` says, and is re-written inline at
  `app/tests/test_engine_offline_run.py:17-22`.
- **Difference:** cost, and a new module identity on every call.
- **Single version:** an importable `co_scientist/testing/` package.
- **Lines saved (measured):** 36.
- **Risk:** keep it out of the production image.
- **Belongs:** phase 5.

#### B-63 OpenRouter catalog fake defined six times

- **Implementations:** two byte-identical autouse fixtures
  (`engine/tests/conftest.py:49-71`, `app/tests/conftest.py:25-46`), plus
  `_llm_fake.py:511-544`, `test_free_model_requests.py:52-64` and two
  script-string copies in `evaluations/tests`.
- **Difference:** three mechanisms. Only one checks the real fetch kwargs.
- **Single version:** a shared `free_catalog()` helper.
- **Lines saved (measured):** 35.
- **Risk:** the evaluation probes run in a subprocess.
- **Belongs:** phase 5.

#### B-64 Fake MCP `call_tool` clients defined six times

- **Implementations:** `engine/tests/_mcp.py:25-57`,
  `_research_fakes.py:131-141,286-297`,
  `test_literature_review_retrieval.py:118-128,162-165`,
  `test_search_tool_retry.py:11-18`.
- **Difference:** failures are declared differently, and `has_tool` is
  missing on one, so a node that calls it raises `AttributeError`.
- **Single version:** one `FakeMcpClient`.
- **Lines saved (measured):** 48.
- **Risk:** keep the three separate interface layers.
- **Belongs:** phase 5.

#### B-65 `call_llm_json` stubbed by hand at 25 sites; no response builder is checked against its schema

- **Implementations:** the helpers `engine/tests/_llm_fake.py:121-151`; 25
  hand-written `monkeypatch.setattr(..., "call_llm_json", ...)` sites; the
  builders `engine/tests/_state.py:45-94`, which no test validates against
  a schema.
- **Difference:** fidelity. A schema change leaves those tests green on
  stale shapes.
- **Single version:** one stub helper plus a schema-validation test.
- **Lines saved (measured):** 7.
- **Risk:** sites that record prompts need a recording helper.
- **Belongs:** phase 5.

#### B-66 Hermeticity enforced differently per suite

- **Implementations:** the app scrubs provider keys and forces offline
  (`app/tests/conftest.py:49-74`); `engine/tests/conftest.py` does neither.
  `test_engine_configuration.py:309-312` re-derives the list of keys.
- **Difference:** behaviour. An engine test that forgets to install a fake
  calls the live provider on a developer machine that has keys set.
- **Single version:** a shared autouse `no_outbound_provider` fixture.
- **Lines saved (measured):** 4.
- **Risk:** needs an opt-out marker.
- **Belongs:** phase 5, or a quick separate fix.

#### B-67 Four ways to put app tests "online"

- **Implementations:** `fake_process_mode` (`app/tests/conftest.py:85-90`),
  `reachable_provider` (`:77-83`), inline environment edits, and 6
  `require_remote_chat` bypasses.
- **Difference:** `FakeProcessMode` ignores BYOK scope (compare
  `app/app/process_mode.py:43-50`).
- **Single version:** `fake_process_mode`.
- **Lines saved (measured):** 10.
- **Risk:** the layer that fires first changes.
- **Belongs:** phase 5.

#### B-68 MCP-server HTTP doubles: two forms

- **Implementations:** `engine/mcp_server/tests/_httpx.py:18-73` (replaces
  the client class) and `:101-118` (`MockTransport`). Both are used in one
  file.
- **Difference:** the stub has no `status_code` or headers.
- **Single version:** `transport_responses`.
- **Lines saved (measured):** 56.
- **Risk:** low.
- **Belongs:** phase 5.

#### B-69 Frontend fetch and `Response` doubles

- **Implementations:** the shared `app/frontend/src/http_test_support.ts`,
  used by 3 files. Ad-hoc doubles appear in `settings_dialog.test.tsx:24-37`,
  `chat_workspace_test_helpers.tsx:73-88`, `runs_qa.test.ts:76-81` and
  `runs.test.ts:178-185`, and `vi.mock('@/api/runs')` is used in 9 places.
- **Difference:** hand-cast objects lack `headers`.
- **Single version:** `src/shared/api/testing.ts`.
- **Lines saved (measured):** 25.
- **Risk:** call-order mocks.
- **Belongs:** frontend lane Part 1.

#### B-70 Frontend render wrappers and fixtures

- **Implementations:**
  - The provider stack is built by hand 7 times.
  - Three `makeRun` functions with different signatures
    (`test_fixtures.ts:30-43`, `run_detail_overview_test_support.tsx:7-18`,
    `run_detail_test_support.tsx:8-22`).
  - `deferred()` is defined three times.
  - There are four chat builders.
- **Difference:** the defaults differ.
- **Single version:** `src/shared/testing/`.
- **Lines saved (measured):** 150.
- **Risk:** keep the defaults as presets.
- **Belongs:** frontend lane Part 1.

## Findings, severity C

Each finding here is severity C (cosmetic) and has a single owning area. In
the engine rows, `co_scientist/` stands for `engine/src/co_scientist/`. The
"Lines" column is measured; 0 means the change swaps values, or that the
saving is already counted under a related finding.

### Engine

| ID | Concept | Implementations | Difference | Single version | Lines | Risk | Belongs |
|---|---|---|---|---|---|---|---|
| C-01 | Truncation and clip helpers | `co_scientist/constants/__init__.py:261-271`, `co_scientist/agents/reflection/review_gate.py:141-145`, `app/app/report/markdown/hypothesis.py:209-213`, `app/app/report/markdown/__init__.py:203-207`, `app/app/qa/manifest.py:342-346`, `app/app/store/events.py:94-100`, `app/app/engine_adapter/drain/reviews.py:150-152`; the marker string appears in `engine/mcp_server/text_extraction.py:63-75` and again in `constants/__init__.py:267` | `...`, `…` or no marker. The suffix may count inside or outside the limit. One report uses two styles | `core/text.py` (`clip`) | 31 | Tests pin some markers, and the marker is model-facing | phase 5 |
| C-02 | "Which UTC day is it" | `co_scientist/llm/attempts/retry.py:108-111`, `app/app/free_usage.py:54-57`, `app/app/provider_usage.py:41`, `co_scientist/llm/admission/free_policy.py:172-173` | None today, but the three reset instants must agree | `core/clock.py` | 10 | None | phase 5 |
| C-03 | ContextVar bind and reset | `co_scientist/_context.py:10-15` (private) versus `app/app/llm_scope.py:41-49`, `app/app/engine_tasks/runtime.py:102-106`, `app/app/credentials.py:345-349`, `app/app/logging_setup.py:28-32`, `app/app/provider_usage.py:19-23` | Same pattern | `core/context.py` (public) | 29 | The architecture test forbids private engine imports | phase 5 |
| C-04 | Stable digests and seeds | `agents/ranking/ranking_matchmaking.py:34-35` (MD5 of goal and iteration, without `run_id`), `ranking_debate.py:179`, `constants/__init__.py:295`, `agents/reflection/deep_verification.py:105-115`, `review_evidence.py:243`, `research/artifacts.py:75-79`, `app/app/claims/grounding.py:72-88`, `app/app/credentials.py:145-162`; an ID-factory trio with no production caller at `models/__init__.py:169-196` | Three canonical-JSON encodings. Two runs with the same goal share pairings | `core/ids.py` | 28 | Fingerprints are persisted, and a new seed reshuffles resumed runs | phase 5 |
| C-05 | Model catalog facts outside `llm/profile/` | `app/app/byok_models.py:11-27`, `app/app/config.py:16,193-199`, `co_scientist/generator/core.py:48`; the pin test `app/tests/test_configuration.py:27-33` covers only some of them | The extra BYOK models are not pinned against pricing | `platform/llm/profile/` | 0 | Low | separate fix (the guard test), then phase 5 |
| C-06 | Thread fan-out with context propagation | `app/app/claims/grounding.py:222-225,255-258`, `app/app/hypothesis/safety.py:161-163`, `app/app/citations/__init__.py:269-270` (no propagation) | The citation pool would lose its ContextVars if an LLM check were ever added | `orchestration/` (`map_in_threads`) | 12 | Low | phase 5 |
| C-07 | Offline-or-BYOK admission written inline | `app/app/offline_guard.py:13-18`, `app/app/runs/chat.py:211,231`, `app/app/runs/crud.py:128,515`, `app/app/engine_adapter/__init__.py:47-75` | Same rule in four places | `domains/access/` | 3 | Privacy-sensitive | phase 5 |
| C-08 | Control-flow error tuple and hierarchy | `co_scientist/exceptions.py:83-86` versus the hand-listed copy in `app/app/claims/verifier.py:81,195`; 9 error classes outside the hierarchy | A newly added control-flow error would not reach the verifier | `core/errors.py` | 2 | Low | phase 5 |
| C-09 | Prompt templating | `co_scientist/prompts/loading.py:19-65` (`{{var}}` renders `MISSING`) versus app `str.format` prompts (`app/app/interviews/questions.py:92,128`, `app/app/claims/verifier.py:323,450`) | A missing key raises in the app but renders silently in the engine | `platform/llm/prompts.py` | 0 | App prompts contain literal braces | phase 5 |
| C-10 | Repeated literals | `'scientist'` reviewer defined 4 times (`app/app/report/markdown/hypothesis.py:518`, `app/app/engine_adapter/drain/reviews.py:403`, `app/app/store/runs_views.py:281`, `co_scientist/models/__init__.py:64`); cap 24 twice (`owed_review.py:12`, `review_gate.py:382`); one constant aliased twice (`evolve_grounding.py:23`, `review_evidence.py:176`); `'openrouter/'` inline 8 times in 4 files | Cosmetic | `core/` constants | 4 | None | phase 5 |

### App backend

| ID | Concept | Implementations | Difference | Single version | Lines | Risk | Belongs |
|---|---|---|---|---|---|---|---|
| C-11 | SSE headers, error frames and event envelope | Framing is shared (`app/app/sse.py:7-8`). Headers differ across `app/app/runs/__init__.py:75-84`, `app/app/interviews/stream.py:95-99` and `app/app/runs/chat.py:142-145`. Error key `message` (`app/app/qa/__init__.py:401,416`) versus `detail` (`interviews/stream.py:47,82,86`). Envelope built in 6 places (`run_events.py:22`, `safety/__init__.py:115,182`, `report/finalize.py:205,206,233`) | Proxy buffering differs for the Q&A stream; two error shapes | `api/sse.py` | 8 | Frontend contract | phase 5 + frontend lane Part 1 |
| C-12 | Small repeats | The private `db._now` is imported by 25 modules while `time.time` is called at 10 sites; raw `BEGIN` at `runs/chat.py:71` and `runs/lifecycle.py:63-66`; the logger `"app.run_stage"` created 3 times; three pagination cursor names; a hidden cap of 200 in `store/interviews.py:135` | `list_interviews` cannot reach the 201st chat | `platform/db`, `api/` | 12 | Low | phase 5 |

### Build and config

| ID | Concept | Implementations | Difference | Single version | Lines | Risk | Belongs |
|---|---|---|---|---|---|---|---|
| C-13 | Ports and hosts as literals | 8888, 8008 and 5173 across the Makefile, compose files, Dockerfiles, `.env.example` files and `vite.config.ts:42-46`; the domain repeated at `app/frontend/scripts/prerender.mjs:13,28,37` | All agree today | One constant per file | 4 | Low | frontend lane Part 1 (vite, prerender) |
| C-14 | Ruff configuration pasted 3 times | `engine/pyproject.toml:61-83`, `app/pyproject.toml:69-91`, `evaluations/pyproject.toml:10-33` | Identical | Root `.ruff.toml` with `extend` | 36 | Verify the CI lint job | phase 5 |
| C-15 | CI path filters overlap | `.github/workflows/ci.yml:54-140`: `engine/**` includes `engine/mcp_server/**` | Wasted CI minutes | – | 0 | – | Not before launch |

### Frontend

| ID | Concept | Implementations | Difference | Single version | Lines | Risk | Belongs |
|---|---|---|---|---|---|---|---|
| C-16 | Menu surfaces | `workbench/layout_primitives.tsx:8-9`, `components/settings_dialog.tsx:771`, `pages/chat_composer.tsx:653` | Three radii; one hand-written shadow | `shared/ui/menu.tsx` | 0 | – | Part 1 |
| C-17 | Radii | 133 radius utilities with 30 distinct values; 44% use the three named invariant values; `rounded-[9999px]` ×23 is the same value as `rounded-full`; chips at `chat_home_stage.tsx:476,479` and `chat_composer.tsx:325` are not `rounded-full` | Breaks the invariant in `app/AGENTS.md:127` | Radius tokens | 0 | Landing visual diffs | Part 1 |
| C-18 | Spacing and type scale | 330 arbitrary spacing utilities (97 distinct); 131 `text-[..]` values (44 distinct); a separate px dialect on the landing page (130 values) | Near-miss values such as 0.82, 0.84, 0.85, 0.86, 0.875 and 0.88 rem | `@theme` scale | 0 | Needs screenshot checks | Part 1 |
| C-19 | z-index | 27 uses with 16 values; `classes.ts:28` and `layout_nav_rail.tsx:42` are both `z-[70]` | DOM order decides the stacking | `--z-*` scale | 0 | Stacking contexts | Part 1 |
| C-20 | Shadows | 6 hand-written in TSX; a card (`chat_home_stage.tsx:472`) and an input (`chat_composer.tsx:85`, documented) carry shadows | Breaks the rule in `app/AGENTS.md:128` | Elevation tokens | 0 | Reference parity | Part 1 |
| C-21 | Tooltips | One CSS mechanism (`styles/tooltips.css`), plus native `title` on 5 elements | OS delay; not shown on keyboard focus | `shared/ui/tooltip.tsx` | 0 | – | Part 1 |
| C-22 | Chips | `components/tabs/ideas_tab.tsx:29-36,227,234`, `run_detail_learning.tsx:461,472,483`, `chat_home_stage.tsx:475-479`, `chat_composer.tsx:325` | Three radii | `shared/ui/chip.tsx` | 0 | – | Part 1 |
| C-23 | Cards, option rows, lists | `settings_dialog.tsx:48-49`, `run_detail_shell.tsx:217,233`, option rows `chat_questions.tsx:124-128` against `chat_timeline_run_spec_card.tsx:383-387`, list padding 1.25 against 1.35 rem | Cosmetic | `shared/ui/surface.tsx` | 0 | – | Part 1 |
| C-24 | Easing and durations | `cubic-bezier(0.2,0,0,1)` ×18 in 6 files; 16 distinct durations; 3 copies of the thinking-dot keyframe (`styles/home_surface.css:3-52`) | Cosmetic | `--ease-*`, `--duration-*` | 36 | Reduced-motion selectors | Part 1 |
| C-25 | External links | `rel="noreferrer"` at `settings_dialog.tsx:242-246` and `run_detail_overview.tsx:228-232`, `rel="noopener noreferrer"` at three other sites; 3 sites render model-supplied URLs with no scheme allow-list | React 19 is the only guard unless the API validates the URLs | `shared/ui/external_link.tsx` | 0 | – | separate fix (check the backend), then Part 1 |
| C-26 | Class composition and icon sizes | `joinClasses` ×72 versus 31 template literals; 11 or more icon sizes; 50 of 53 `<Icon>` uses pass `aria-hidden`, which is already the default | Cosmetic | `<Icon size>` (edit the generator) | 0 | `icon.tsx` is generated | Part 1 |
| C-27 | Ellipsis in UI text | `...` ×6, for example `run_detail_specifications.tsx:55`, versus `…` ×7, for example `:171` in the same file | Ignores the stated single-glyph preference (`chat_timeline_thoughts.tsx:23-24`) | A copy convention | 0 | Tests assert the strings | Part 1 |
| C-28 | Micro helpers | `isRecord` (`lib/text.ts:76-78`, `chat_session_start_run.ts:416-418`); list joining (`run_spec.ts:181-185` with an Oxford comma, `run_detail_overview.tsx:652-655` without); pluralize (`lib/text.ts:108-110`, `run_detail_overview.tsx:307-309`) | Punctuation | `shared/lib/text.ts` | 15 | – | Part 1 |
| C-29 | Status checks that bypass the predicate helpers | `run_detail_data.ts:74-75`, `run_detail_shell.tsx:209`, `chat_home_stage.tsx:717-718` | Caught by `tsc` | `shared/api/run_status.ts` | 0 | – | Part 1 |
| C-30 | "Elo rating" label | `lib/hypotheses.ts:32-38` (says "Unranked" when unplayed) versus `run_detail_overview.tsx:284,336` (always shows the rating) | An unplayed idea can show "Elo rating: 1200" | `features/report/format.ts` | 2 | – | Part 1 |
| C-31 | API URL building | `hooks/use_run_stream.ts:84-87`; 18 path templates without `encodeURIComponent`, against 2 sites that encode; 14 hand-written `clientHeaders()` | Inconsistent | `shared/api/http.ts` | 18 | Public endpoints must stay anonymous | Part 1 |
| C-32 | Client-side ID generation | `lib/client_id.ts:12-17` versus `chat_composer.tsx:362-364` (`Math.random`) | Cosmetic | `shared/lib/ids.ts` | 1 | – | Part 1 |

### Tests

| ID | Concept | Implementations | Difference | Single version | Lines | Risk | Belongs |
|---|---|---|---|---|---|---|---|
| C-33 | App test SSE parsers, run creators, waiters | `_parse_sse` written 5 times (`app/tests/test_run_integration.py:193-198`, `test_task_recovery.py:345-348`, `test_safety.py:448-453`, `_interviews_helpers.py:43-51`, `test_run_stream_keepalive.py:32`); `_new_run` 3 times; `_make_run` with 3 meanings; `make_client` skips the app lifespan while 28 sites run it | Cosmetic; the lifespan split is undocumented | `app/tests/_client.py` | 47 | None | phase 5 |
| C-34 | Freezing time and suppressing sleep | 4 forms each, for example `app/tests/test_status_probe_cache.py:13-30` and `engine/tests/test_checkpoint.py:133-134` | Cosmetic | `tests/_time.py` | 11 | None | phase 5 |
| C-35 | Redundant `@pytest.mark.asyncio` | 101 markers, although `asyncio_mode = "auto"` (`engine/pyproject.toml:99`, `app/pyproject.toml:122`) | No-op | – | 101 | None | phase 5 |
| C-36 | Frontend mock cleanup | 26 manual restore calls in 21 files; `app/frontend/vite.config.ts:30-37` sets neither `restoreMocks` nor `unstubGlobals` | Cosmetic | Vitest config | 26 | Stubs relied on across tests | Part 1 |
| C-37 | E2E setup repeated | The theme init script 7 times; the YouTube stub twice with different bodies; a literal client ID at `e2e/tests/07_mobile_interview.spec.ts:10,39` instead of `CLIENT_ID` (`e2e/support/fixtures.ts:13`); inline viewports; no lint config | Cosmetic | `e2e/support/fixtures.ts` | 16 | None | Part 1 |
| C-38 | Small builders | `_MODEL`/`_SCHEMA` twice; `byok_secret` with two different values (`app/tests/test_byok_models.py:17-19`, `test_credentials.py:19-22`); one dict literal twice in `app/tests/_report_helpers.py:8-14,24-28` | Cosmetic | Shared helpers | 15 | None | phase 5 |

## Intentional differences

These look like duplication, but a comment or a document gives the reason.
They are not counted as findings. Where the documented reason covers only
part of a duplication, the rest is a finding and the table names it.

| Concept | Where | Documented reason |
|---|---|---|
| Three app copies of the "reasoned but wrote nothing, retry once with thinking off" step | `app/app/interviews/model.py:487-509`, `app/app/goal_text.py:148-171`, `app/app/run_start_announcement.py:180-201` | `docs/OPERATIONS.md:71` ("without importing that ladder"). It covers the copies, not the different detectors (B-20) or the missing Q&A retry (A-08) |
| App stream deadlines (silence and total) versus the engine's blocking ceiling | `app/app/llm_scope.py:146-182`, `engine/src/co_scientist/llm/request/completion.py:103-130` | `engine/AGENTS.md:253`, `docs/OPERATIONS.md:71` ("bound silence, not duration") |
| Two MCP call paths report timeouts differently | `engine/src/co_scientist/mcp_client/__init__.py:362` and `:373-385` | `docs/OPERATIONS.md:75` (raising would kill sibling calls under `gather`) |
| Two wall-clock ceilings, 600 s for the LLM and 300 s for MCP | `completion.py:24-25`, `mcp_client/__init__.py:244-246` | `docs/OPERATIONS.md:75` |
| JSON-schema capability read in two places | `completion.py:67,156`, `llm/attempts/json_attempt.py:19,122` | `engine/AGENTS.md:253` ("read in two places on purpose") |
| Process-local log rate limit versus durable SQLite limits | `app/app/logs_api.py:20-21` | The single-replica rule in `AGENTS.md` (Production hosting). It does not cover the race in A-09 |
| `threading.Lock` for cross-cohort state, per-loop semaphores for batches | `llm/admission/call_budget.py:68`, `agents/ranking/ranking_debate.py:547-570` | `AGENTS.md` operational invariants; `docs/OPERATIONS.md:63` |
| Interactive chat surfaces swallow exceptions around LLM calls | `app/app/interviews/questions.py:133`, `goal_text.py:152-165`, `run_start_announcement.py:214-217` | Module docstrings: these are not durable tasks |
| Raw deferred `BEGIN` for read snapshots | `app/app/runs/chat.py:69-71`, `app/app/store/db.py:88-90` | "Q&A reads must not acquire SQLite's single writer" |
| Contextual versus deterministic safety failure returns | `app/app/safety/__init__.py:322-324,361-363` | The docstrings; `docs/OPERATIONS.md:88-93` |
| Safety uses a 5-state active set, the run code a 3-state set | `app/app/safety/__init__.py:153-176` | The docstring: no late safety stop after cancellation |
| The run stream also ends on PAUSED | `app/app/runs/events.py:12-18` | The code comment |
| Graph-node callers versus durable-task callers of the same scientific operations | `agents/reflection/review.py:303-308` against `app/app/engine_tasks/fanout_aggregates.py:367-400`; `agents/ranking/ranking.py:55` against `app/app/engine_tasks/ranking.py:122-125` | `engine/AGENTS.md:50-52,56-60`; `app/AGENTS.md` ("Scientific operations stay engine-owned") |
| Per-consumer abstract caps (1500, 2000, 3000, 4000 characters) | `evidence/relevance.py:36-38`, `deep_verification_evidence.py:14-16,103-106`, `research_overview_evidence.py:174-177` | A rationale comment at each site |
| Different coverage thresholds for citations and claims | `app/app/citations/__init__.py:327-332` | The comment there. The thresholds are intentional; the tokenizer split is not (A-04) |
| The MCP server keeps its own copies (URL guard, DOI regex, truncation marker) | `engine/mcp_server/*` | The MCP server is a separate package with no engine dependency (`engine/mcp_server/pyproject.toml:25-36`, `engine/AGENTS.md:425,436`). This justifies MCP-side copies, but not the app's copy of the URL guard (B-30) |
| Two MCP Dockerfiles, IPv6 for Railway and IPv4 locally | `Dockerfile.mcp:1-3`, `engine/mcp_server/Dockerfile:1-2` | `docs/DEPLOYMENT.md:26` |
| Two API Dockerfiles, Railway and compose | `Dockerfile.api:2`, `app/docker/Dockerfile.api:2` | `app/AGENTS.md` (Docker workflow) |
| `app/requirements-app.txt` mirrors `app/pyproject.toml` | `app/requirements-app.txt:1-21` | `AGENTS.md` (Working in this repo), enforced by `app/tests/test_architecture.py:178` |
| Frontend wire types | `app/frontend/src/api/wire_*.ts` | Generated from `app/app/api_contracts/`, checked by `app/tests/test_architecture.py:190-217` |
| `clean_markup` and `clean_snippet` unescape in opposite orders | `engine/mcp_server/tools/lit_review/europepmc_search.py:50-52`, `engine/mcp_server/tools/web_providers.py:20-22` | The comments: escaped source markup, and not re-creating tags |
| Three app run recipes (root Makefile, `app/Makefile`, pixi) | `Makefile:151`, `app/Makefile:7,10`, `app/pyproject.toml:53-58` | `AGENTS.md`: "Each project is also independently installable and runnable" |
| `.dockerignore` per build context | root, `engine/`, `app/`, `app/frontend/` | Docker reads only the context's own file |
| `th-*` versus `cosci-*` colour families | `app/frontend/src/index.css:43-200` | `app/AGENTS.md:124`. The landing page's `--l-*` palette is not documented (B-46) |
| Some buttons keep transitions in CSS | `layout_header.tsx:32-33`, `home_landing.tsx:79`, `chat_home_stage.tsx:78-79` | The unlayered global `button` rule would beat a utility |
| The composer shadow exists in light mode only | `chat_composer.tsx:73-74` | "Composer elevation is light-only in the reference" |
| No always-on document key handler | `workbench/hooks/dom.ts:191` | `app/AGENTS.md:156` |
| `listDemoRuns` omits the client ID | `app/frontend/src/api/runs.ts:70-72` | `api/runs.ts:606` |
| JSON parsing and stream framing kept separate | `api/runs.ts:582,621` | `app/AGENTS.md` (HTTP clients) |
| The run stream swallows errors and reconnects | `hooks/use_run_stream.ts:16,104-107` | The comments: replay is safe because of sequence de-duplication |
| Diagnostics are event-driven, while history and status poll | `layout_diagnostics.tsx:53-54`, `history_context.tsx:72-75` | `app/AGENTS.md:114`. The hidden-tab cost is in B-57 |
| Pending prose is escaped; final prose is Markdown; a separate inline-HTML sanitizer | `components/markdown_message.tsx:40-41`, `lib/sanitize_html.ts:1-2` | `app/AGENTS.md` (run detail) |
| A legacy activity table for events recorded before classification | `run_detail_activity_log.tsx:353-369` | The code comment |
| Engine tests install the bare fake; app tests wrap it in `OfflineRouter` | `engine/tests/_llm_fake.py:86-96`, `app/tests/_llm_fake_backend.py:33-41` | The comment at `:33-34`; `engine/AGENTS.md:253` |
| `install_fake_llm` forces `supports_json_schema=True` | `engine/tests/_llm_fake.py:188-190` | The comment there |
| Evaluation probes carry the fake as script text | `evaluations/tests/_engine_fake_backend.py:1` | The comment: subprocess probes |
| `Hypothesis.from_dict` strips computed fields | `engine/src/co_scientist/models/__init__.py:214-215,317-318` | The comment there |

## Clean concepts

These have one implementation that the rest of the code uses. They show
where the codebase is already consolidated, and they are evidence for the
per-area verdicts.

- **Engine:**
  - The LLM physical-call transport, `complete_request`
    (`engine/src/co_scientist/llm/request/transport.py:84-121`). Every app
    model call goes through `app/app/llm_request.py:26`.
  - Retry classification and quota parking
    (`llm/attempts/retry.py:55-130`).
  - The jitter math (`engine/src/co_scientist/backoff.py:4-15`).
  - Fence stripping and JSON repair (`llm/structured/validate.py:134-146,289-306`).
  - The schema builders (`schemas/builders.py`), which the app uses too.
  - Token estimation (`llm/tools/policy.py:25-35`).
  - Call budgets (`llm/admission/call_budget.py:23-131`).
  - Model facts (`llm/profile/__init__.py:112-262`): no model-name branching
    happens anywhere else.
  - Prompt template loading (`prompts/loading.py:19-38`).
  - The Elo update (`agents/ranking/ranking_debate.py:381-397`).
  - Hypothesis ID minting (`models/__init__.py:162-168`).
  - The rankable and undermined predicates (`models/__init__.py:304,310`).
  - `is_blocking_status` (`safety.py:181`).
  - The hypothesis pool reducer (`state/__init__.py:119-131`).
  - RRF fusion (`evidence/search_fusion.py:178-205`).
  - The meta-review prompt context (`prompts/_common.py:74-120`).
  - Subprocess execution, only in `sandbox/runner.py:144,216`.
  - The control-flow error tuple (`exceptions.py:84`).
  - There is no duplicated LLM response cache.
- **App backend:**
  - SQLite connections and transactions (`app/app/store/db.py:36-98`);
    there is one `sqlite3.connect`, at `:44`.
  - Event append and sequence allocation (`store/events.py:136-176`).
  - SSE framing (`sse.py:7-8`).
  - The async/thread bridge (`async_bridge.py:36-129`).
  - The durable queue: one table, and notifications reuse it
    (`notifications.py:84-90`).
  - Client identity (`auth.py:16-22`).
  - The offline decision (`process_mode.py:63`).
  - Run serialization (`store/models.py:63-82`).
  - The title cleaner (`goal_text.py:110-118`).
  - Free-tier admission (`free_usage.py:36-48`).
  - Logging bootstrap (`logging_setup.py`).
  - The provider credential map (`config.py:168-190`).
- **MCP server:**
  - The tool registry, manifest and logging wrapper
    (`engine/mcp_server/server.py:96-128`, `tool_logging.py:107`).
  - The Entrez seam (`entrez.py:111`).
  - Cache path confinement (`pubmed_storage.py:10-36`).
  - The shared-secret middleware (`auth_middleware.py:15-46`).
  - Web provider fallback state (`tools/web_providers.py:27-62,232-273`).
- **Cross-cutting:**
  - Generated wire types.
  - The activity vocabulary, which a test guards
    (`app/app/api_contracts/common.py:25-37`).
  - `RunStatus` and the terminal set (`app/app/store/models.py:11-30`).
  - The e2e ports (`e2e/support/paths.ts:19-20`).
  - One base-image digest across the four production Dockerfiles.
- **Frontend:**
  - One raw `fetch` (`app/frontend/src/api/runs.ts:548`).
  - One server-error extractor (`api/runs.ts:525-543`).
  - One SSE parser (`api/runs.ts:621-640`).
  - One set of request headers (`api/runs.ts:490-512`).
  - One Markdown renderer (`components/markdown_message_renderer.tsx`).
  - One inline-HTML sanitizer (`lib/sanitize_html.ts:16`).
  - One error boundary (`components/error_boundary.tsx:109`).
  - One clipboard write (`lib/clipboard.ts:3`).
  - One tab resolver (`workbench/run_tabs.ts:19-26`).
  - The status predicates (`api/runs.ts:124-176`).
  - A generated icon set (`components/icon.tsx:162`).
  - One tooltip mechanism (`styles/tooltips.css`).
  - The dialog primitives (`workbench/hooks/dom.ts:174-327`).
  - Smooth scrolling (`lib/smooth_scroll.ts`).
  - Debouncing (`run_detail_data.ts:276-300`).
  - Zero `dark:[#hex]` overrides.
- **Tests:**
  - The temporary SQLite fixture (`app/tests/conftest.py:60-74`, 1,346
    references).
  - `make_client` (`app/tests/_client.py:30-51`).
  - The store seeders (`app/tests/_store_helpers.py:32-83`).
  - `make_state` (`engine/tests/_state.py:129-142`).
  - The engine builders (`_state.py:17-42`).
  - `FakeSseBody` (`app/frontend/src/http_test_support.ts:27-57`).
  - The global test stubs (`app/frontend/src/test_setup.ts:7-40`).
  - The e2e `CLIENT_ID` fixture (`e2e/support/fixtures.ts:13`).

## Other observations

These are not duplication, but the audit found them while reading, and they
mislead the next reader.

- `docs/REARCHITECTURE.md` reached `main` in
  [guy915/Co-Scientist#335](https://github.com/guy915/Co-Scientist/pull/335)
  while this audit ran. Its text is identical to the version on the plan PR
  ([guy915/Co-Scientist#329](https://github.com/guy915/Co-Scientist/pull/329)),
  which is the one the audit used.
- `engine/AGENTS.md:253` has two errors:
  - It cites five test files that are not in git:
    `test_llm_layering.py`, `test_llm_completion_routing.py`,
    `test_config_registry.py`, `test_llm_attempt_loop_tools.py`,
    `test_model_profile_snapshot.py`.
  - It says `isolate_offline_router` lives in `tests/_llm_fake.py`. It is
    in `engine/tests/_mcp.py:105`.
- `docs/OPERATIONS.md:73` cites `literature_tools/validate_search.py` and
  `tests/test_tool_param_contract.py`. Neither exists.
- `docs/ARCHITECTURE.md:190` cites `lib/api_key.ts`, which no longer exists.
  The BYOK keys moved to `app/frontend/src/lib/client_id.ts`.
- `app/AGENTS.md:114` says the log capture hooks stay mounted with the Logs
  button. `app/frontend/src/main.tsx:18-19` installs two of them globally.
- `app/app/engine_adapter/events.py:17-18` says its stage list is derived
  from the engine's nodes. It is a literal list (B-18).
- jscpd reports 31,812 frontend production lines against 23,963 by `wc -l`,
  because it counts TSX under more than one format. The frontend
  percentages in the summary table are jscpd's own ratios.

## Blind spots of this method

- **Clone detectors** find exact and token-level copies only. They cannot
  see near-misses or "same concept, different code". Every A finding came
  from the name or concept passes.
- **The structural hash** strips names and literals but keeps exact shape.
  A second implementation with one extra branch hashes differently. It
  missed the buttons entirely, because JSX elements are not functions.
- **The name-based pass** finds only synonymous names. Two implementations
  with unrelated names, like `_check_rate` and `admit`, are found only by
  the concept pass.
- **The literal pass** filtered Python strings by pattern (URLs, model ids,
  env names) and skipped small numbers (0-5, 10, 100). A repeated domain
  string such as a status word is found only through the concept pass
  (B-09).
- **The concept pass** depends on the brief's concept list and on what the
  auditors read. Large files were skimmed, not read line by line:
  - `literature_tools/validate.py`, `draft.py`, `ranking_debate.py`,
    `scheduling/policy.py`, the `workspace/` and `sandbox/` internals,
    `patch/`
  - the landing page (about 2,200 lines)
  - `report/markdown/*` beyond the identity and truncation helpers
  - `engine_tasks/*` beyond the concepts listed
- **Prompt text** in `prompts/templates/*.md` was not compared for wording
  duplication; only the Python formatters were.
- **Execution:** nothing was executed except small read-only probes in the
  project venv, which reproduced A-01, A-04, A-05 and A-06 and the
  engine-science claims in B-02.
  - A-07 (MCP tools other than arXiv), A-08, A-09 and the frontend A
    findings come from reading the code, not from a running system.
  - No browser was run, so no light/dark screenshots were taken. Token
    parity was checked from the token tables only.
- **Dynamic class strings** (for example `tone-${x}`) and CSS rules behind
  `reference-*` and `ucs-*` hooks are not resolved by the frontend counts.
- **"Lines saved"** sums redundant ranges before adding back the shared
  version. Some entries overlap (A-08 and B-20 are counted apart on
  purpose). Treat the totals as an upper bound on deletion, not a plan.
- **Persisted values:** whether a consolidation changes persisted values
  (fingerprints, idempotency keys, dedup keys, safety policy versions) is
  flagged under Risk. It was not tested.

## Verdict per area

| Area | Verdict | Evidence |
|---|---|---|
| Engine (`engine/src`) | **Isolated** | The cores have one implementation each: transport, retry loop, backoff, JSON repair, schema builders, model profiles, Elo, the pool reducer (see [Clean concepts](#clean-concepts)). Clone rates are 0.04% at 6/60 and 0.46% at 4/40. The 29 concepts with more than one implementation cluster in one band: shaping model and tool output (B-02, B-03, B-04, B-07, B-12), domain vocabularies (B-09, B-15) and cross-package edges. The 3 A findings sit at boundaries with the app (A-01, A-03, A-05). |
| App backend (`app/app`) | **Isolated** | Connections, transactions, SSE framing, the async bridge, the queue, event append, identity and offline mode each have one implementation. Clone rates are 0.06% and 0.35%. Duplication is in small helpers: status sets, JSON column decoding, BYOK parsing, ownership checks, limiters. Two copies disagree in user-visible ways (A-02, A-08), and one races (A-09). |
| MCP server (`engine/mcp_server`) | **Pervasive in the tool layer** | The registry, Entrez seam, auth and cache confinement are single. But each of the 21 tools decides its own policy: 6 failure conventions (A-07), 12 HTTP client constructions with 3 different `trust_env` settings (B-32), 2 pacers (B-33), 3 HTML cleaners (B-34), 2 PubMed parsers (A-06) and 6 record shapes (B-31). There is no shared tool scaffold. |
| Frontend (`app/frontend/src`) | **Pervasive in the UI layer; isolated in the data layer** | UI: no `shared/ui`. 50 buttons with 45 class recipes; 30 distinct radii, 44% of them invariant-compliant; 196 hard-coded media queries; 44 font sizes; 3 palettes; 25 focus-ring variants; 2 toast systems; 3 outside-click hooks. Data: one `fetch`, one SSE parser, one error extractor, one Markdown renderer. Clone rates are near zero (0.03% and 0.12%) because the duplication is in class strings, not in code. |
| Tests (all suites) | **Pervasive in test doubles** | 3 fake-backend scripters (B-58), 2 schema-filling fakes that have drifted (B-59), 6 stream builders and a fake that sets a field production never reads (B-60), 6 catalog fakes (B-63), 6 MCP client fakes (B-64), 25 inline `call_llm_json` stubs (B-65), 7 hand-built provider stacks (B-70). The measured volume is small, about 773 lines or 1.7% of test code. The cost is fidelity: fakes that production code would reject. |
| Build and config | **Isolated** | Most values agree, though they are repeated. Two pairs disagree (B-38), and one compose healthcheck is weaker (B-36). |
| Evaluations | **Clean** | 0% clones at 6/60; 15 lines in 2 clones at 4/40. No finding is owned here. It shares the tier tuple (B-17), a stopword list (A-04) and the fake loader (B-62) with other areas. |

## Overall answer

**Targeted consolidation. No area needs a rewrite.**

The owner suspected that the frontend button pattern runs through the whole
codebase. The measured answer: it runs through the frontend UI layer, the
MCP tool layer and the test doubles. In the other areas, a single shared
implementation exists for each core concept and is used; the duplication
there is in helper code around those cores.

What follows from that:

1. **Before launch: the 13 A findings, as separate fixes.**
   - Fix first, because each is cheap and user-visible: safety tiers
     (A-01), redaction fields (A-02, which needs an owner decision),
     publication order (A-03), the citation tokenizer (A-04), citation
     keys (A-05), the PubMed placeholder string (A-06), retrieval failures
     reported as empty results (A-07), Q&A (A-08) and storage guards
     (A-10).
   - The B findings marked "separate fix" are small:
     - the `research_adapter` crash (B-02)
     - the skills-path split (B-06)
     - the swapped `make_tool_call` (B-61)
     - the compose healthcheck and the sandbox digest (B-36)
     - the CI version disagreements (B-38)
     - the 429 counted as "not found" (B-33)
     - the per-card timers (B-57)
2. **Frontend lane Part 1: build `src/shared/ui` and `src/shared/lib`,
   then migrate.** That means a Button, IconButton, Field, Dialog, Menu,
   Toast and state components, plus radius, z-index, breakpoint, easing and
   type tokens, plus the shared hooks for media queries, dismissal, copy,
   polling and storage (B-40 to B-57, C-16 to C-32). This is the one place
   where the work is building a missing layer rather than merging two
   copies. It is still a migration of existing screens, not a rewrite.
3. **Phase 5: one concept per PR, as the plan prescribes.** The largest
   items:
   - one retrieval result contract and transient retry in
     `platform/retrieval` (A-07, B-01, B-02, B-31)
   - one safety rule table (A-01, A-02)
   - one tokenizer (A-04)
   - one tier table (B-17)
   - one stage vocabulary (B-18)
   - an app stream helper (B-20)
   - typed vocabularies (B-09)
   - an importable test-support package (B-58 to B-65)
4. **The MCP server needs a small tool scaffold inside its own package.**
   That means one HTTP client factory, one empty-or-failed result helper,
   one pacer and one record shape (B-30 to B-35). It stays separate from
   the engine, as the plan requires.

### Totals

- **Findings:** 121 concepts with more than one implementation: 13 at A, 70
  at B, 38 at C.
- **Clean:** the clean list above comes from about 290 checked concepts.
  That count includes overlap between the seven auditors.
- **Duplicated lines:** production clones are 0.08% at 6 lines/60 tokens
  and 0.39% at 4 lines/40 tokens. Tests are 0.21% and 0.97%.
- **Measured redundant lines** across all findings: 3,423, an upper bound.
  Production code accounts for 2,502 of them, about 2.6% of 96,147 lines;
  test code for 773, about 1.7% of 45,236; build configuration for 148.

The size of the problem is consistency and correctness, not volume.
