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
| [fidelity-audit/](fidelity-audit/README.md) | **The authoritative gap analysis** vs. Google's Co-Scientist and Hypothesis Generation: [FINDINGS.md](fidelity-audit/FINDINGS.md) (every gap, deduplicated from three audits) and [PLAN.md](fidelity-audit/PLAN.md) (the sequenced work). It does not credit `FIDELITY.md`, `PARITY.md`, or `UI-FIDELITY.md` as evidence — where they disagree with it, they are the ones that are wrong. |
| `assets/` | Screenshots and SVG diagrams used by the docs |

## Historical records (dated; not updated)

| Entry | Contents |
|---|---|
| [PUBLICATION-REVIEW.md](PUBLICATION-REVIEW.md) | 1 October 2026 cleanup validation, secret-detector triage, and outstanding publication gates |
| [PARITY-VERIFICATION.md](PARITY-VERIFICATION.md) | Point-in-time record (2026-07-10) of how parity claims were verified: commands, results, and honest limitations. The live ledger is [PARITY.md](PARITY.md) |
| [PROMPT-PRESERVATION.md](PROMPT-PRESERVATION.md) | Record (2026-09-01, rows updated 2026-09-06) auditing each of the eight published prompts (`docs/CORPUS-EXTRACTION.md` Appendix A) instruction-by-instruction against its corresponding template, beyond the `MP-*` checklist's spot findings. All eight now render verbatim and in published order; the live per-template provenance is `engine/src/co_scientist/prompts/templates/README.md` and the standing check is `engine/tests/test_published_prompt_fidelity.py` |
| [CORPUS-STATUS.md](CORPUS-STATUS.md) | Point-in-time record (2026-09-02) re-classifying every `work`/`unclear` row in `docs/CORPUS-EXTRACTION.md` as BUILT/OPEN/DECISION/FALSE, checked against the code and git history rather than the table |
| `decisions/` | Dated decision records |
| [archive/](archive/README.md) | Retired prototypes and pointers to completed campaign evidence |
| `superpowers/plans/` | Dated implementation plans |
| `superpowers/specs/` | Dated design specs |
