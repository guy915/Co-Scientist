# Coding-harness reference sources

Upstream coding-agent implementations cloned for design analysis ahead of
building an execution/coding harness inside Co-Scientist. The clone trees are
**gitignored** (~730 MB of third-party code, not ours to redistribute); this
manifest and the `_analysis/` write-ups are committed.

Rehydrate any row with:

```bash
git clone --depth 1 https://github.com/<repo> references/harness/<dir> && \
  git -C references/harness/<dir> fetch --depth 1 origin <sha> && \
  git -C references/harness/<dir> checkout <sha>
```

| Dir | Repo | Pinned SHA | License | Cloned | Analysis |
| --- | --- | --- | --- | --- | --- |
| `OpenHands/` | `All-Hands-AI/OpenHands` | `b25f9b3969f924f37440fee908ff35309ec6eea2` | MIT | 2026-08-18 | `_analysis/openhands.md` |
| `opencode/` | `sst/opencode` | `4e81a0b73f6e614afebf9c7ff8862904a3674455` | MIT | 2026-08-18 | `_analysis/opencode-codex.md` |
| `codex/` | `openai/codex` | `a397079287e6638b39dda329835350d93222681f` | Apache-2.0 | 2026-08-18 | `_analysis/opencode-codex.md` |
| `openevolve/` | `codelion/openevolve` | `411fb59c886c18704caaffb611e17cf9e7d824d2` | Apache-2.0 | 2026-08-18 | `_analysis/openevolve.md` |
| `pi_agent_rust/` | `Dicklesworthstone/pi_agent_rust` | `2861aa83e87d136837085fdee4e4f9694ca4ed6f` | MIT **+ rider — see below** | 2026-08-18 | **none — analysis halted** |

## Licence notes

Four of the five are plain permissive (MIT / Apache-2.0) and safe to study and
to reimplement from, with attribution.

**`pi_agent_rust` is not.** Its LICENSE is MIT plus an "OpenAI / Anthropic
Rider" that materially changes the grant:

- **Restricted Parties** = OpenAI, Anthropic, their affiliates, and anyone
  "acting directly or indirectly on behalf of, for the benefit of, or under
  the direction of" them. No rights whatsoever are granted to them.
- **"Use" is defined to include** "executing, benchmarking, testing,
  **analyzing**, indexing, or incorporating the Software or any Derivative
  Works into any dataset, training corpus, **evaluation harness, or pipeline
  for machine learning or other automated systems**."
- The rider **propagates to derivative works** and must be redistributed
  unmodified; breach terminates the licence automatically.

Two consequences for this project:

1. Having an Anthropic model read and analyze this repository is plausibly the
   exact activity the rider names. The planned analysis was **halted** for that
   reason; no `_analysis/pi-agent.md` exists.
2. More importantly, porting its design would arguably make Co-Scientist a
   derivative work, which would drag the rider along — permanently encumbering
   this codebase with a clause requiring it be withheld from two named AI labs
   and carried forward verbatim. That is a poison pill for a project that is
   otherwise cleanly licensed.

**Recommendation: treat `pi_agent_rust` as off-limits for porting.** The
capabilities it demonstrates are all present in the permissively licensed
alternatives above. This is an engineering read, not legal advice; if Pi Agent
is important to you, it is worth a lawyer's eye or a note to the author.
