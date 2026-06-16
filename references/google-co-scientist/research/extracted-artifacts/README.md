# Co-Scientist — extracted artifacts

The **reusable pieces** pulled out of the Google AI Co-Scientist papers and
supplements in `../papers/` and `../supplements/`: the prompts its agents were
given, the algorithm pseudo-code, and the outputs it produced. Everything here
is **verbatim** from those sources (this folder **augments** them — it does not
replace them; the papers and supplements remain the source of truth).

## What's here
| Folder | What it is |
|---|---|
| `prompts/` | The **8 agent prompts** (generation ×2, reflection, ranking ×2, evolution ×2, meta-review), one per file. |
| `pseudocode/` | The Co-Scientist agents' **pseudo-code** (one listing covering all agents). |
| `outputs/` | The **outputs the system generated**, grouped by case study — **generated hypotheses**, **full reports** (research overviews + tournament rankings), reflection reviews, ranking debates, meta-review critiques, validated outputs, NIH Specific-Aims, deep-verifications, and a tool-use (AlphaFold) example. |

## Tracing back to source
Most extracted files begin with a `<!-- SOURCE: <original path> · <section> · <lines> -->`
header. The `outputs/atypical-protein-assemblies/` set (19 generated hypotheses
+ 3 reports + the research goal) is copied verbatim from the already-organized
case study under `../supplements/ai-guided-discovery-of-atypical-protein-assemblies/`
— see the `NOTE.md` in that folder.

## Completeness
Every source document was read in full and cross-checked, so the prompts,
pseudo-code, and output examples here are the complete set of distinct artifacts
the sources contain. (The running prose of the papers — methodology, results,
references — lives only in the originals, which is why you keep them.)

> Naming is lowercase kebab-case to match the repo's `references/` convention.
