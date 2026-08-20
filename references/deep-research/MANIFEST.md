# Deep-research reference sources

Upstream deep-research implementations cloned for design analysis ahead of
deepening Co-Scientist's literature-exploration and grounded-verification
paths. The clone trees are **gitignored** (~62 MB of third-party code, not ours
to redistribute); this manifest and the `_analysis/` write-ups are committed.

Rehydrate any row with:

```bash
git clone --depth 1 https://github.com/<repo> references/deep-research/<dir> && \
  git -C references/deep-research/<dir> fetch --depth 1 origin <sha> && \
  git -C references/deep-research/<dir> checkout <sha>
```

| Dir | Repo | Pinned SHA | License | Cloned | Analysis |
| --- | --- | --- | --- | --- | --- |
| `open_deep_research/` | `langchain-ai/open_deep_research` | `1b7d2e80db9faa586165c60e09096dbbfd483a64` | MIT | 2026-08-20 | `_analysis/open-deep-research.md` |
| `gpt-researcher/` | `assafelovic/gpt-researcher` | `5d84d2f5553e70a2765a8ff3a0d2672d60437ce8` | Apache-2.0 | 2026-08-20 | `_analysis/gpt-researcher.md` |
| `storm/` | `stanford-oval/storm` | `fb951af7744dab086e34962e9bc6fe878e145f83` | MIT | 2026-08-20 | `_analysis/storm.md` |

## Licence notes

All three are plainly permissive and were checked firsthand in the clone rather
than taken from the survey in `references/peripheral/deep-research-agent/`:

- `open_deep_research` — MIT, © 2025 LangChain.
- `gpt-researcher` — Apache-2.0 (NOTICE-style attribution required on reuse).
- `storm` — MIT, © 2024 Stanford Open Virtual Assistant Lab.

All three are therefore safe both to **study** and to **copy code from**, with
attribution. Apache-2.0 (`gpt-researcher`) additionally requires that its
licence and any NOTICE travel with copied source, so a lifted file must keep a
provenance header. Nothing here carries a field-of-use rider of the kind that
made `pi_agent_rust` off-limits in the previous (coding-harness) cycle.

## Freshness

Last commit dates at clone time: `open_deep_research` 2026-08-10 (active),
`gpt-researcher` 2026-07-14 (active), `storm` 2025-09-30 (quiet for ~11 months
— treat it as a design source to learn from, not a dependency to track).
