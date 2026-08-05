# Work plan

The remediation queue for [FINDINGS.md](FINDINGS.md), in the order to do it.

Every item below is a defect: the system doing something wrong, with a
consequence. Findings already closed on `main`, and findings that record a
deliberate local design choice, are not carried here — [FINDINGS.md](FINDINGS.md)
remains the full register.

## Stages

| Stage | Theme | Size |
|---|---|---|
| 1 | Five correctness bugs | medium |
| 2 | Stop presenting degraded state as normal | small |
| 3 | Remove controls that report success for nothing | small |
| 4 | Wire what is already built | small |
| 5 | Engine reasoning | large |
| 6 | Durable state and safety | medium |
| 7 | Grounding | medium |
| 8 | Observability | small |
| 9 | Security, privacy, packaging | large |
| 10 | Accessibility and responsive | small |
| 11 | Adaptive coalition | large |
| 12 | Evaluation | external-dependent |
| 13 | Documentation | ongoing |

Stages 1–4 are the near-term queue: independent of each other apart from one
noted dependency. Everything after is sequenced by dependency, not urgency.

Check `AGENTS.md` before editing. Several of the modules below have a current
shape that is a recorded production incident fix — the SQLite write lock,
VACUUM, thinking budgets, coverage-versus-Jaccard scoring, the review gate,
echoed schemas, the proximity graph. Those comments are the reasoning; extend
them rather than re-deriving from first principles.

---

## Stage 1 — Five correctness bugs

**Closes:** D5, F1, E2, I1, J5

Do these first and in this order. Each is independently shippable.

1. **`D5` — the public share leaks raw run data.** `shares.get_shared_report`
   returns `store.list_hypotheses()` and `store.list_evidence()` verbatim, so a
   share token exposes blocked ideas, private document text, and run
   configuration. Return the same filtered release artifact the report path
   already builds. *Smallest fix here, and the only one whose harm lands on
   someone other than the run's owner — hence first.*
2. **`F1` — an exhausted task leaves the run `running` forever.**
   `store.fail_task` marks the *task* failed and touches no run state; nothing
   else transitions the run. No error, no terminal event, SSE never closes,
   `cosci runs wait` hangs until a process restart. Settle the run
   transactionally: failed run, terminal event, error surfaced to API/SSE/CLI.
   Nothing may stay non-terminal with no claimable work.
3. **`E2` — user-supplied starting hypotheses are silently dropped.**
   `generation_debate_and_literature.md` requires `{{user_hypotheses}}` and
   `{{instructions}}`; none of `_build_debate_base_variables`,
   `_build_debate_literature_variables`, or `_build_debate_guidance_variables`
   produces either, so both render as `{{MISSING:...}}` on every turn of the
   production path.
4. **`I1` — rejected content reaches the published overview.**
   `research_overview.py:62` passes `state["hypotheses"]` straight to
   `_summarize_top_hypotheses`, which Elo-ranks the whole pool with no
   disposition, safety, or claim filter. Filter **before** the LLM call — never
   post-filter prose already synthesized from blocked ideas.
5. **`J5` — uncertain hypotheses vanish.** `held_for_review` is written
   throughout the engine and read nowhere in `app/`. Either surface it or stop
   dropping into it; silently discarding work is not an option.

**Done when:** an integration test injects one of each kind of blocked idea and
asserts absence from the share payload and the overview; a task driven past its
retry budget settles its run to `failed` end to end; a run with starting
hypotheses proves they reach the debate prompt.

---

## Stage 2 — Stop presenting degraded state as normal

**Closes:** B9, C1, C6, D18, G11, L7

Five findings, one defect wearing five hats: the UI renders a failure
indistinguishably from a success. Worth doing as one batch because the judgement
call is the same each time.

- **`B9`** — failed, cancelled, and blocked runs still render full report tabs.
- **`G11`** — a run whose literature retrieval returned nothing still reads
  categorically; mark ungrounded output conspicuously.
- **`L7`** — eight schemas degrade to empty structures after five failed
  attempts, visible only as a WARNING. The reader sees a blank section.
- **`D18`** — `Evidence.available` is never surfaced, so a source that was never
  reachable renders identically to one that was fetched.
- **`C6`** — `use_run_stream.ts:76` states outright that connection drops are not
  surfaced. A frozen page looks healthy.
- **`C1`** — progress moves backward: fixed phase constants let deep
  verification report 81–84 and proximity then report 75–85, and the home card
  retains the furthest phase with `Math.max`.

`C1` is the monotonicity of the reported phase, not the shape of the bar. The
progress bar stays indeterminate: work is spread over durable tasks of very
uneven duration, so a percentage would have to be invented, and an invented one
is exactly the kind of confident-but-false signal this stage exists to remove.

---

## Stage 3 — Remove controls that report success for nothing

**Closes:** M11, A14 (partial), A16, A17

Mostly deletions.

- **`M11`** — Settings accepts a DeepSeek API key, saves it, and confirms
  success. It goes to `localStorage` and nothing reads it. Remove the field; the
  panel already discloses that runs use the deployment's provider.
- **`A14`** — remove the decorative lock icon from the composer. It implies
  encryption that does not exist. (Scope is the icon; the surrounding copy is
  settled.)
- **`A17`** — disable the home composer once a run starts; it currently keeps
  posting turns into a completed interview.
- **`A16`** — signal the keyless/offline interview fallback instead of silently
  serving a canned three-question script.

---

## Stage 4 — Wire what is already built

**Closes:** D11, D12 — then, on product judgement, D4, A7, A8

The server side of these is built, tested, and unreachable.

1. **`D12`** — report download. `/report.md` exists with nothing linking it.
2. **`D11`** — share create/list/revoke. All three endpoints live in
   `shares.py`. **Depends on `D5`** — the share payload must be sanitized before
   a UI makes shares easy to create.

The next three are also fully built server-side, but each adds real UI surface
to a product whose owner considers the UI settled. **Confirm with the repository
owner before building any of them:** Chat with Agent (`D4`, `askRunQuestion`),
mid-run steering (`A7`, `sendRunSteering`), scientist contribution (`A8`).

Two related items are *not* wiring: run deletion (`N3`) has no endpoint at all
and belongs to stage 9, and the completion email (`B8`) is blocked on production
SMTP environment variables, which is the repository owner's change to make.

---

## Stage 5 — Engine reasoning

**Closes:** E1, E4–E20, H2, H4–H9, K3–K9, G13, A2

1. Make full/simulation/recurrent review outputs actually feed ranking,
   evolution, meta-review, and the report (`E1`). They are computed at LLM and
   retrieval cost and read by nothing — even fatal findings change no
   disposition.
2. Add sub-assumption decomposition and decontextualization to deep
   verification; run it on post-tournament leaders rather than an all-tied pool;
   make provider failure an explicit unverified state, not an implicit pass
   (`E4`, `E9`).
3. Add the sixth evolution operator and split coherence/feasibility out of
   `ENHANCEMENT` — there are five, selected round-robin by
   `(index + iteration) % 5`. Add literature retrieval to grounding-enhancement,
   and support multi-parent (`parent_ids`) combination (`E5`, `E6`, `E10`).
4. Thread the meta-review critique into Proximity, Literature Review, Safety,
   and the observation review — it currently reaches none of them (`E7`).
5. Novelty grounding is gated on `state["mcp_available"]`; when MCP is down the
   system reproduces the un-tooled failure mode Google measured, 6.14 → 2.38/10
   (`E8`).
6. Re-enable agentic literature exploration — `enable_tool_calling_generation`
   is set only in tests — and make research expansion a distinct technique;
   implement iterative assumption trees (`E11`, `E12`).
7. Make debate turn counts a 3–5 / max-10 range, parse the `HYPOTHESIS`
   termination token, re-enable diversity angles on the durable path
   (`E13`, `E14`, `E16`).
8. Finish `A2`: scientist evaluation criteria are now collected and threaded
   into engine opts — confirm they reach ranking and debate prompts, and let
   them govern scoring (`A2`, `K4`).

---

## Stage 6 — Durable state and safety

**Closes:** F2, F3, F6, F7, F9, J1, J2, J3, J4, J6, J8, J10, B3, B5, A9, A11, N9

1. A safety hold has no claimable successor — the holding task already
   succeeded, so approval reuses a completed idempotency key and nothing
   resumes. Make the hold an explicit durable waiting state (`F2`).
2. Upsert scientist hypotheses without the `UNIQUE constraint failed:
   hypotheses.id` collision, preserving id, author, provenance, lineage, and
   safety state (`F3`, `F7`).
3. Commit steering consumption and its successor checkpoint atomically (`F6`);
   bound every fan-out and isolate per-item failures (`F9`).
4. Strengthen the intake gate to parity with the per-hypothesis gate — "design a
   bioweapon for mass-casualty deployment" blocks per-hypothesis but is only
   dual-use at intake (`J1`).
5. Finish `J2`: the provider-credential table is now unified, so DashScope
   resolves correctly, but the semantic screen still falls back to regex-only on
   a missing credential with no log line. Make that failure closed, or at
   minimum loud.
6. Finish `J3`: the engine redacts hypothesis fields in place; confirm app-side
   goal and report-Markdown redaction, and that the original is unreadable
   through DB, API, SSE, log, share, and export.
7. Invalidate the cached graph and tool availability on configuration change
   (`B5`); make create → upload → start one recoverable transaction (`A11`) and
   let attachments ground the interview (`A9`); ensure forced offline makes no
   external request (`N9` — the interview and Q&A paths currently call the real
   provider whenever a key is reachable).

---

## Stage 7 — Grounding

**Closes:** G1, G2, G5, G6, G7, G9, G10, G12, G14, I4

1. **`G1` — settle the policy first, with the repository owner.** Contradicted
   ideas are withheld from the report; merely-unsupported ones publish with an
   "Unverified" badge. That is a deliberate-looking behavior with no recorded
   decision behind it, so confirm it is intended before building on it. If it
   is, record it in FINDINGS.md and close the row.
2. Finish `G2`: a progressive broadening ladder retries queries that return
   nothing (`query_broadening.py`). Still missing MeSH, OR expansion, and field
   tags — and confirm the final fallback no longer sends the whole prose goal
   verbatim to Entrez.
3. Finish `G6`: retraction detection exists across metadata shapes; the
   reserved-slot and underfilled-budget admission paths were never traced and
   may still select a retracted source.
4. Add semantic or hybrid retrieval with persisted scores, rationale, and
   version (`G5`); canonical DOI/PMID identity, availability checks, retrieval
   timestamps, and exact stored passages (`G12`), fed to Q&A, reviews,
   verification, reports, and citations (`G9`).
5. Fix the Knowledge Base evidence links reading a nonexistent edge-level
   `evidence_id` (`G7`). Add cache invalidation keyed to model, prompt, tool,
   and source version (`I4`).

---

## Stage 8 — Observability

**Closes:** L2–L6, L14, plus the metrics half of F5

`prompt_tokens`/`completion_tokens` are parsed off the response
(`llm_response.py:45`) and then discarded — nothing persists or surfaces them,
and there is no cost accounting. Instrument every model and tool call with
agent, task, model, prompt, tool, schema and policy version, tokens, cost,
latency, retries, errors, cache state, and item yield. Fix the `max_llm_calls`
undercount (`L3`). Add live in-flight metrics (`L14`) and a health check that
reflects real run health — `/health` is store reachability plus an import
lookup, so a wedged run, failed task, stalled worker, and full disk all report
`healthy` (`L6`). Stage 11's allocator cannot work without truthful counters.

---

## Stage 9 — Security, privacy, packaging

**Closes:** all remaining N

Independent of everything else and separately shippable. Ordered by exposure:

1. **Security:** `N1` (auth defaults to `compatibility`, trusting a
   caller-selected `X-Client-ID`), `N2` (`access_token` read from the query
   string at `auth.py:104` and appended by `runs_http.ts:39`), `N7` (the MCP
   server is unauthenticated with wildcard CORS — currently intentional and
   commented, so make the call explicitly rather than by default), `N6`
   (self-declared audience), `N14` (diagnostic disclosure), `N32` (missing
   security headers).
2. **Data lifecycle:** `N3` (no run/report/document deletion — the only DELETE
   route is share revocation), `N4` (retention and cascade), `N5` (upload MIME
   is caller-supplied, no signature or malware check), `N11`, `N12`.
3. **Packaging:** `N15` (Tesseract absent from images), `N16`, `N17`, `N18`.
4. **Gate honesty:** `N20`, `N21`, `N23`, `N24` (one Chromium project; E2E
   writes into tracked `docs/assets`), `N25` (offline runs are exempt from the
   empty-leaderboard block at `report_render.py:405`), and finish `N19` (root
   `lint` omits frontend gts).
5. **Deployment:** `N29`, `N28`, `N30`, `N31`, `N33`, `N10`.
6. **Documentation truth:** `N26`, `N27`, `N36`.

`N6` needs the note in FINDINGS.md about `paper_corpus.disabled_tools_for()`
before it is touched: the audience selector is the corpus access control.

---

## Stage 10 — Accessibility and responsive

**Closes:** all of O, M2, M3, M12

Implement focus trap, inert background, and opener restoration (`O1`); finish
the master/detail semantics — idea rows carry `aria-current` but no
listbox/option relation to the detail pane (`O2`, `O3`); remove `role=status`
from interactive popovers (`O4`); keep streaming status concise and non-live
(`O5`); choose one coherent navigation-or-tab semantic and implement its
keyboard behavior (`O6`). Fix the 720-CSS-pixel boundary so 16:9 and 2:1 both
render without clipping (`M2`); confirm the Back control in
`run_detail_shell.tsx:123` is reachable as the mobile idea-detail escape (`M3`).
Make global shortcuts discoverable or remove them (`M12`).

Verify every change in both light and dark themes, and measure dark from a real
capture rather than by eye.

---

## Stage 11 — Adaptive coalition

**Closes:** F4, F5, F10, F11, F12, E19, I2, I3

The architectural gap, and the largest item here. Attempt only after stages 1,
6, and 8, since it moves the execution model everything else runs on.

Scope is the **allocator over the durable queue**, not the queue. The queue
itself — leases, heartbeats, idempotency, per-node checkpoints, working resume
— was independently confirmed sound by all three audits and stays.

1. Replace the fixed serial spine and single-successor enum with
   dependency-aware queueable tasks (`F4`).
2. Give the Supervisor a real allocation contract: enqueue a bounded portfolio,
   observe queue depth and measured agent yield, reprioritize at safe
   boundaries. `performance_assessment` is written at `supervisor.py:254` and
   read by nothing (`F5`). Remove the prompt instruction forbidding workflow
   planning.
3. **Feed the research overview back into Generation** (`I2`) — it is strictly
   terminal today, with no consumer in generation or supervisor — and make
   mature review outputs causally effective (`I3`, with `E1` from stage 5).
4. Make evolution stagnation-gated (`F10`); persist the plan, allocations,
   observations, and terminal rationale (`E19`).

---

## Stage 12 — Evaluation

**Closes:** L8–L12, L15, J7, K3

Mostly evidence acquisition, not code: the GPQA / Elo-correctness concordance
harness (`L8`), a controlled multi-budget scaling curve (`L9`), strategy and tool
ablations (`L11`), a blinded expert panel (`L10`), evaluation artifacts with full
provenance (`L12`), and an expanded adversarial safety set (`J7`).

**`L15` (wet-lab validation) cannot be closed in this repository** and stays
explicitly open. Fixtures and anecdotes are not substitutes for it.

---

## Stage 13 — Documentation

**Ongoing.** Rewrite README, architecture, fidelity, parity, env, setup, and
deployment docs from current executable evidence. Describe the roster as
Supervisor plus six specialists.

Keep the evidence-boundary register in [FINDINGS.md](FINDINGS.md) current. Mark
a boundary item resolved only when new primary evidence appears, never because
code was written against a guess.

---

## Working notes

- **Verify before starting an item; the register can lag the tree.** The
  2026-08-05 pass found six findings already fixed that a commit-subject reading
  had left open, and one whose commit subject read as a fix but had only changed
  the policy. Read the code.
- **Land behavior with a test that fails without it.** An earlier campaign
  closed 86 findings; several were absent again eight days later.
- **One run path.** The durable `engine_tasks` path is the only one; the legacy
  streaming path was removed. Audit text describing two paths is stale.
