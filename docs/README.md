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
| [PARITY-VERIFICATION.md](PARITY-VERIFICATION.md) | How parity claims are verified |
| [RUNNING-LOCALLY.md](RUNNING-LOCALLY.md) | Running the app locally, incl. the git-worktree gotchas |
| [UI-FIDELITY.md](UI-FIDELITY.md) | Visual/UX fidelity audit of the workbench vs. the reference product |
| [fidelity-audit/](fidelity-audit/README.md) | **The authoritative gap analysis** vs. Google's Co-Scientist and Hypothesis Generation: [FINDINGS.md](fidelity-audit/FINDINGS.md) (every gap, deduplicated from three audits) and [PLAN.md](fidelity-audit/PLAN.md) (the sequenced work). It does not credit `FIDELITY.md`, `PARITY.md`, or `UI-FIDELITY.md` as evidence — where they disagree with it, they are the ones that are wrong. |
| `assets/` | Screenshots and SVG diagrams used by the docs |

## Historical records (dated; not updated)

| Dir | Contents |
|---|---|
| `decisions/` | Dated decision records |
| `superpowers/plans/` | Dated implementation plans |
| `superpowers/specs/` | Dated design specs |
