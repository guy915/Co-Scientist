# Analysis — Google DeepMind Science Skills

Primary source: *Science Skills for Antigravity: Towards Efficient and Reliable
Scientific Workflows*, Google DeepMind, 2026-05-19
([PDF](https://storage.googleapis.com/deepmind-media/papers/google_deepmind_science_skills_for_antigravity_towards_efficient_and_reliable_scientific_workflows.pdf)).
Read in full for this analysis. Numbers below are the report's own; earlier
third-party figures circulating for this work (a "~39% progressive-disclosure
saving", a "~89% script-vs-codegen saving") **do not appear in it** and should
not be repeated.

## What a skill is

A skill is a directory of instructions the agent loads on demand. The bundle
follows the cross-vendor [Agent Skills standard](https://agentskills.io/),
which the report describes as doing three things: *guide behavior* (instructions
like a system prompt), *provide resources* (point at files, APIs, tools), and
*program in English* (step-by-step algorithmic instruction).

Concretely:

```
skills/<name>/
  SKILL.md          frontmatter: name, description   <- all the agent sees up front
  scripts/*.py      uv-run argparse CLIs, subcommand per workflow step
  references/*.md   API docs, query-field tables, worked examples
```

The frontmatter is the routing surface. A description is written to say both
what the skill is for **and what it is not** — `foldseek_structural_search`
ends "Do NOT use if the user only provides a protein sequence, gene name, or
UniProt ID"; `protein_sequence_msa` names four sibling skills to use instead.
Negative routing is as prominent as positive routing throughout the bundle.

## The measured claim

67 internal capability tasks, binary success, LLM-autorated. Two base models,
Antigravity with and without the bundle:

| Agent | Reliability without | Reliability with |
| --- | --- | --- |
| Gemini 3 Flash | 49% [37, 61] | **93%** [87, 99] |
| Gemini 3.1 Pro | 67% [57, 78] | **91%** [84, 97] |

| Agent | Mean tokens/task without | with | Gain |
| --- | --- | --- | --- |
| Gemini 3 Flash | 13,952 | 6,827 | 2.04× |
| Gemini 3.1 Pro | 5,828 | 3,588 | 1.62× |

External benchmark, BioReason (Flash only): VEP-Coding 41.4% → 60.9%
(n=1,233), VEP-Non-SNV 46.6% → 81.6% (n=873). The KEGG subset was skipped for
licensing.

**The headline is the one worth carrying: Flash *with* skills beats Pro
*without*, on both reliability and cost.** The gap between the two base models
disappears once skills are present, to within the evaluation's sensitivity.

Note what the token saving is not. It is not a context-window trick — the
report attributes it to trajectory shape, and Appendix B shows why. Without
skills the agent runs 11–20 turns of web search, `curl`, and repeated `grep`
against downloaded pages, hallucinating a database link along the way; with
skills it reads one `SKILL.md`, runs one CLI subcommand to a JSON file, and
greps that. **Fewer, better-aimed steps, not smaller ones.**

## The design rules, as the bundle states them

`skills/workflow_skill_creator/SKILL.md` is the bundle's own authoring
standard. The rules that transfer regardless of format:

1. **Reuse over reimplementation.** A new skill whose workflow touches an
   existing skill's ground *must* reference it by name and list it under a
   `Dependencies` section. There is no self-contained option.
2. **Default to file output, never stdout.** Stdout carries a one-line status
   and the output path; results go to a file the agent then queries for the
   fields it needs. Stated reason: API responses truncate in terminal output
   and large stdout wastes the context window.
3. **Make `--limit` required, with no default.** So the agent cannot silently
   believe it retrieved everything when it was quietly capped.
4. **Put the response body in non-retriable HTTP errors.** A 400's body says
   which parameter was wrong; a bare status code leaves the agent unable to
   self-correct.
5. **Rate limits are looked up, documented, and enforced in code**, defaulting
   to 1 req/s when no published limit can be found; enforcement is a
   cross-process file lock so concurrent sub-agents on one machine share the
   budget.
6. **Fixed `SKILL.md` section order**, ending in *Common Mistakes* — 2–3
   pitfalls stated as prohibitions.
7. **Cap skill output at 500 lines or redirect it to a file.**

Rule 5 used to be implemented in-tree by `scienceskillscommon/http_client.py`
(833 lines, stdlib only — `urllib`, no third-party transport): per-API rate
limiting via `fcntl` file locks, jittered exponential backoff, `Retry-After`,
and `X-Throttling-Control` proactive backpressure for PubChem/NCBI. **In
v1.1.0 that module is gone from the repository** and lives on PyPI as
`polite-http`, which 51 scripts import. The behaviour is unchanged; what
changed is that reading the bundle no longer tells you what the rate limiter
does, and shipping the bundle no longer ships it.

## What the prose carries that a tool signature cannot

The largest `SKILL.md` files are mostly operational judgement with no home in
an API schema or a typed manifest. From `uniprot_database` alone: always
`count` before `search` or `stream`; `stream` for bulk and it ignores
`--limit`; pivot to SPARQL when REST cannot express the query, and always for
exact sequence match; broad text search returns citation noise because UniProt
indexes publication titles, so prefer `cc_function:`/`protein_name:`; `name:`
is not a field; UniParc holds non-model organisms UniProtKB does not; never
assume the meaning of an ontology ID without looking it up.

This is the part of the bundle that is genuinely not portable into a tool
signature, and it is also the part most likely to move a reliability number.

## Stated limitations

- **The Agent Skills standard has no reproducible-environment story.** Skills
  must otherwise be authored to survive arbitrary user desktops, which the
  team found hurt reproducibility badly enough that they imposed `uv` as a
  standardised environment and accepted the resulting constraints. They say
  outright they would prefer the standard to cover this.
- **Coverage is a starting point, not a map.** Science is too wide to cover by
  bundling; hence the meta-skill for users to author their own.
- **Long-running workflows are out of scope.** The bundle targets tasks of
  dozens of steps, a few hours, half a dozen skills. Nothing longer was
  evaluated, and they note that the longer a task runs the more user
  interaction with work in progress matters.

## Bearing on this repository

- The reliability result is the interesting one for us, not the token one. A
  hypothesis-generation run's cost is dominated elsewhere; a run's *grounding*
  is not.
- The rules in 2, 3, 4 and 7 above are already this repo's instincts in
  different words — bounded tool output (`workspace/output.py`), a barrier
  vocabulary for concurrency (`tool_effects.py`), tool errors returned as tool
  results rather than raised (`tools/provider.py::execute_tool_call`).
  Rule 3 is the one we do not have: several tool parameters here carry silent
  defaults.
- The environment limitation is the reverse of our position. Their
  reproducibility problem is arbitrary user desktops; ours is a single
  controlled container image, where `uv` is one line of a Dockerfile. The
  constraint that forced their design is one we do not have.
- The negative-routing convention in descriptions is directly applicable to
  `prompt_snippet` in `config/tools.yaml`, which today says only what a tool is
  for.


## What running it taught, that reading it did not

Two things about executing this bundle inside a confined workspace are not
visible anywhere in the bundle or the report, and both were found by running
it.

**`uv run` cannot be used inside the sandbox.** uv's cache layout contains a
directory literally named `.git` (`sdists-v9/.git`). `.git` is in
`sandbox/policy.py::PROTECTED_METADATA_NAMES`, so the confinement that exists
to stop a command rewriting the history of a repository it was handed also
stops uv initialising its cache:

```
error: Failed to initialize cache at `...`
  Caused by: failed to open file `.../sdists-v9/.git`: Operation not permitted (os error 1)
```

Moving the cache inside the workspace does not help — the protection applies
to writable roots, which is exactly where it has to live. The answer is not to
run uv at all: resolve the closure once at image build into an ordinary venv
and invoke the scripts with that interpreter. A PEP 723 header is inert
metadata to a plain `python`, so the scripts stay byte-identical to upstream
and only the invocation differs from what `SKILL.md` describes.

**A skill denied the network hangs rather than failing.** Run confined with
`network_allowed=False`, `uniprot_tools.py get P04637` produced no output and
no error; it blocked until the harness's 120s ceiling and was killed
(`rc=-15`). With the network permitted the same command returned the live
Swiss-Prot entry. So a misconfigured policy costs a full timeout per call, not
a fast failure — the runner has to bound skill commands tightly and treat a
timeout as a configuration signal, not a slow API.

**And the bundle's own rule 4 is load-bearing, not stylistic.** That same
`get` wrote its entire response to stdout, which the harness truncated at its
1 MB inline ceiling. Any subcommand offering `--output` must be given one.
