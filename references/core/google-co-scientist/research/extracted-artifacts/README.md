# Co-Scientist — extracted artifacts

The **reusable pieces** pulled out of the Google AI Co-Scientist papers and
supplements in `../papers/` and `../supplements/`: the prompts its agents were
given, the algorithm pseudo-code, and the outputs it produced. Everything here
is **verbatim** from those sources (this folder **augments** them — it does not
replace them; the papers and supplements remain the source of truth).

## What's here
| Folder | What it is |
|---|---|
| `prompts/` | The **8 agent prompts** (generation ×2, reflection, ranking ×2, evolution ×2, meta-review), one per file. This is the complete published set — both the arXiv report (Appendix A.2) and the Nature supplement (Note 9) print exactly these 8; the system runs more review modes, but their prompts were never published. |
| `pseudocode/` | The agents' **pseudo-code**, split **per agent** (`01-supervisor` … `07-meta-review`). The source (Nature SI Note 8) prints it as one integrated listing whose Supervisor loop orchestrates every agent; the per-agent files are its constituent functions. |
| `outputs/` | The **outputs the system generated**, organized **by type** (see below). |

### Output types (`outputs/`)
| Folder | What it is |
|---|---|
| `hypotheses/` | Generated hypotheses (Generation agent) — incl. the full **19-hypothesis** protein-assemblies run under `hypotheses/protein-assemblies/`. |
| `research-overviews/` | The **full reports** / research overviews (Meta-review) — incl. the protein-assemblies reports + tournament rankings. |
| `reviews/` | Reflection-agent reviews (novelty, critiques, full review, deep verification, observation review). |
| `ranking-tournament/` | Tournament debate matches (Ranking agent). |
| `meta-review-critiques/` | Meta-review critiques. |
| `specific-aims/` | NIH Specific-Aims-formatted proposals (Givosiran, Selinexor, Lapatinib). |
| `validated-outputs/` | Full validated outputs (KIRA6, with its critiques + references). |
| `plan-configs/` | Supervisor research-plan configuration. |
| `tool-use/` | Tool-use worked example (AlphaFold). |
| `research-goals/` | The research goals fed in (run inputs). |

## Tracing back to source
Most extracted files begin with a `<!-- SOURCE: <original path> · <section> · <lines> -->`
header. The protein-assemblies hypotheses (`outputs/hypotheses/protein-assemblies/`)
and reports (`outputs/research-overviews/protein-assemblies/`) are verbatim copies
of the already-organized case study under
`../supplements/ai-guided-discovery-of-atypical-protein-assemblies/` — see the
`SOURCE-NOTE.md` in each of those folders.

## Completeness
Every source document was read **in full** and cross-checked, so the prompts,
pseudo-code, and output examples here are the complete set of distinct artifacts
the sources contain. (The running prose of the papers — methodology, results,
references — lives only in the originals, which is why you keep them.)

> Naming is lowercase kebab-case to match the repo's `references/` convention.
