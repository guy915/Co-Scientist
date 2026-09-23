# K-Dense-AI/scientific-agent-skills — source dossier

**State:** M6 acquisition and inventory in progress. No upstream setup script, agent workflow, dependency install, or scientific service has been run.

## Pinned source and reuse boundary

- Upstream: [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills), pinned at [`49c6e97775eaa18ba791bebe23162a70ae601c18`](https://github.com/K-Dense-AI/scientific-agent-skills/commit/49c6e97775eaa18ba791bebe23162a70ae601c18). The clean, filtered local checkout is ignored at `references/work/k-dense-scientific-agent-skills/` and is temporary.
- The root [LICENSE.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/LICENSE.md) declares MIT and copyright 2025 K-Dense Inc. Individual script, data, model, and service terms require separate assessment before adoption; the root license alone does not settle them.
- The pinned tree has 2,484 tracked files and 166 `skills/*/SKILL.md` files. [`plugin.json`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/plugin.json) declares version 2.69.0 and the Agent Plugins schema. A full source and local-coverage inventory follows below.

## Evidence limits

K-Dense's [resource paper](https://arxiv.org/html/2609.00065v2) describes a 163-skill earlier snapshot and explicitly reports no task-level evaluation or host selection rate. At that older tag, resident descriptions used 14,246 tokens (7.1% of a 200,000-token window), and loading every reference file would overflow the window in 29 of 46 documented workflows. Its CI ran only 20 of 105 script-bearing skill suites, and none of its gates established scientific validity. These figures are context for assessing this pinned 166-skill tree, not measurements of our host. Selected techniques must pass this campaign's real harness and scientific-boundary checks; the whole catalog will not be installed.

## Source architecture and operational assumptions

The tree stores one skill per `skills/<slug>/` directory, with a `SKILL.md` instruction file and optional `scripts/`, `references/`, and `assets/`. [`docs/skills.md`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/docs/skills.md) lists all 166 exactly once under documentation categories; it is not a runtime selector. The frontmatter's name and description are the routing surface, while compatibility and allowed-tools describe host assumptions. The [`plugin.json`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/plugin.json) manifest packages the whole tree for plugin-capable hosts. It supplies no confined execution runtime or Co-Scientist integration by itself.

| Documentation family | Skills |
|---|---:|
| Scientific Databases & Data Access | 10 |
| Scientific Integrations | 11 |
| Scientific Packages | 128 |
| Scientific Thinking & Analysis | 17 |

All 166 declare name, description, and metadata version; 162 declare a license, 119 compatibility, and 102 allowed-tools. The pinned tree has 106 script-bearing skill directories with 535 Python, 2 shell, and 122 XML/XSD support files. There are 130 test modules across 107 skill suites. [`tests/skill-requirements.toml`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/tests/skill-requirements.toml) lists 162 skill dependency entries, including 18 marked unavailable; version and interpreter requirements can conflict. The upstream [`tests/run_all.py`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/tests/run_all.py) isolates suites with `uv` and may download packages or interpreters. Neither it nor upstream agent workflows were run here. Source inspection and the paper distinguish tests of structural or script behavior from scientific validity.

The repo's [`scan_skills.py`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/scan_skills.py) can send skill text to a credentialed LLM and defaults to a model without a verified free billing path. Other skills can call OpenRouter, Parallel, lab, clinical, or cloud services; their `allowed-tools` strings are advisory, not a sandbox. Campaign experiments must omit ambient credentials, keep metered services unavailable, and use the current workspace's confinement and provenance controls. A local validator is only a structural check, not evidence that a hypothesis is scientifically correct.

## Component terms and attribution

Four bundled document-format skills, `docx`, `pdf`, `pptx`, and `xlsx`, declare proprietary terms in their own `LICENSE.txt` files, so the root MIT license does not authorize copying them. The `deepspot-m` skill declares PolyForm Noncommercial 1.0.0, `what-if-oracle` declares CC BY-NC-SA 4.0, three skills have unknown terms, and four omit a license field. The [`CITATION.cff`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/CITATION.cff) requests a paper citation and the exact release or commit. Any selected component needs its own terms, author metadata, script dependencies, and data/model licenses checked before reuse. No upstream code has been copied.

## Comparison targets, not adoption decisions

The [`hypothesis-generation`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/skills/hypothesis-generation/SKILL.md) skill includes evidence-led rival predictions and local validators; [`scientific-brainstorming`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/skills/scientific-brainstorming/SKILL.md) has decision registers; [`peer-review`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/skills/peer-review/SKILL.md) has claim/evidence audit scaffolds; and [`experimental-design`](https://github.com/K-Dense-AI/scientific-agent-skills/blob/49c6e97775eaa18ba791bebe23162a70ae601c18/skills/experimental-design/SKILL.md) documents controls and randomization. Database and paper-lookup skills include reproducible retrieval rules. Their local counterparts, overlaps, and actual workflow value must be assessed before any integration. The root README's database-family count and license-field generalization differ from the pinned catalog and frontmatter census; the tracked files govern this assessment.
