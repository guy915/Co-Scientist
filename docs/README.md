# docs/

Index of project documentation. **Live** docs are maintained and safe to cite;
**historical** entries are dated point-in-time records — read them for context,
but do not update them to match later changes.

## Live documents

| Doc | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture across app, engine, and MCP server |
| [CI.md](CI.md) | CI pipeline: jobs, gates, and their local `make` equivalents |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Production hosting: the three deployed services, their Dockerfiles, env vars, and networking |
| [EXPLAINER.md](EXPLAINER.md) | End-to-end walkthrough of how a run executes through the engine graph |
| [FIDELITY.md](FIDELITY.md) | Behavioural/engine fidelity vs. Google's AI Co-Scientist (defers to PARITY.md) |
| [PARITY.md](PARITY.md) | Parity ledger, machine-checked by `make parity` |
| [PARITY-SOURCES.md](PARITY-SOURCES.md) | The arXiv preprint and the Nature SI are two different publications that disagree on some facts; disambiguates a bare "the paper"/"Nature paper" citation in PARITY.md |
| [RUNNING-LOCALLY.md](RUNNING-LOCALLY.md) | Running the app locally, incl. the git-worktree gotchas |
| [LAUNCH.md](LAUNCH.md) | Release validation, deployment configuration, backups, and launch prerequisites |
| [OPERATIONS.md](OPERATIONS.md) | Incident rationale for persistence, worker, provider, and scientific safeguards |
| [../SECURITY.md](../SECURITY.md) | Vulnerability reporting and deployment security boundaries |
| [DEPENDENCY-SECURITY.md](DEPENDENCY-SECURITY.md) | Advisory audits, patched dependency floors, and scoped remaining findings |
| [../requirements/README.md](../requirements/README.md) | Updating hash-pinned production runtime dependencies |
| [UI-FIDELITY.md](UI-FIDELITY.md) | Visual/UX fidelity audit of the workbench vs. the reference product |
| [fidelity-audit/](fidelity-audit/FINDINGS.md) | **The authoritative gap analysis** vs. Google's Co-Scientist and Hypothesis Generation: [FINDINGS.md](fidelity-audit/FINDINGS.md) (every gap, deduplicated from three audits) and [completed plan](https://github.com/guy915/Co-Scientist/blob/5ef0530ede8607b6cc39a6ec06274327bd10cd09/docs/fidelity-audit/PLAN.md) (the sequenced work). It does not credit `FIDELITY.md`, `PARITY.md`, or `UI-FIDELITY.md` as evidence — where they disagree with it, they are the ones that are wrong. |
| `assets/` | Screenshots and SVG diagrams used by the docs |

## Historical records (dated; not updated)

| Entry | Contents |
|---|---|
| [Frontend loading performance (2026-10-02)](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/decisions/2026-10-02-frontend-loading-performance.md) | Deferred route/Markdown boundaries, measured initial bundle reduction and local performance evidence |
| [Dependency audit snapshot (2026-10-02)](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/decisions/2026-10-02-dependency-audit.json) | Advisory IDs, detector-listed fixes and hashes for all five audited locks; reachability review in DEPENDENCY-SECURITY.md |
| [Provider policies (2026-10-02)](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/decisions/2026-10-02-provider-policies.md) | Owner-approved tool retry/parking and independent app budgets on shared transport |
| [Architecture review (2026-10-01)](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/decisions/2026-10-01-architecture-review.md) | Completed package/boundary campaign, verification evidence and deferred architecture decisions |
| [Second architecture pass (2026-10-02)](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/decisions/2026-10-02-architecture-second-pass.md) | Shared operations, dependency ownership, frontend request races and validation |
| [Engine operation boundaries plan (2026-10-02)](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/superpowers/plans/2026-10-02-engine-operation-boundaries.md) | Forward Ranking, Reflection and Evolution boundary tasks, escalation boundedness fix and acceptance checks |
| [Public engine operations (2026-10-02)](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/decisions/2026-10-02-engine-operation-boundaries.md) | Completed boundary continuation, preserved execution adaptations and finite provider recovery |
| [PUBLICATION-REVIEW.md](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/PUBLICATION-REVIEW.md) | 1 October 2026 cleanup validation, secret-detector triage, and outstanding publication gates |
| [PARITY-VERIFICATION.md](https://github.com/guy915/Co-Scientist/blob/5ef0530ede8607b6cc39a6ec06274327bd10cd09/docs/PARITY-VERIFICATION.md) | Point-in-time record (2026-07-10) of how parity claims were verified: commands, results, and honest limitations. The live ledger is [PARITY.md](PARITY.md) |
| [PROMPT-PRESERVATION.md](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/PROMPT-PRESERVATION.md) | Record (2026-09-01, rows updated 2026-09-06) auditing each of the eight published prompts (`docs/CORPUS-EXTRACTION.md` Appendix A) instruction-by-instruction against its corresponding template, beyond the `MP-*` checklist's spot findings. All eight now render verbatim and in published order; the live per-template provenance is `engine/src/co_scientist/prompts/templates/README.md` and the standing check is `engine/tests/test_published_prompt_fidelity.py` |
| [CORPUS-STATUS.md](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/CORPUS-STATUS.md) | Point-in-time record (2026-09-02) re-classifying every `work`/`unclear` row in `docs/CORPUS-EXTRACTION.md` as BUILT/OPEN/DECISION/FALSE, checked against the code and git history rather than the table |
| [decisions](https://github.com/guy915/Co-Scientist/tree/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/decisions) | Dated decision records |
| [External-reference campaign](../PLAN.md) | Completed conclusions, source assessments and immutable links to the archived execution record and receipts |
| [superpowers/plans](https://github.com/guy915/Co-Scientist/tree/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/superpowers/plans) | Dated implementation plans |
| [superpowers/specs](https://github.com/guy915/Co-Scientist/tree/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/superpowers/specs) | Dated design specs |
