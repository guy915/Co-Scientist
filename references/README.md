# references/

Intentionally empty.

This directory held the Google AI Co-Scientist reference tree
(`core/google-co-scientist/`): the paper and Nature supplement, the extracted
prompts, pseudocode, worked outputs, product captures, and long-form analysis.
It was removed on 2026-09-10 once the fidelity replication reached parity on
every disclosed, buildable behavior.

## Where the content went

- **Publishable artifacts** — the eight prompts, seven pseudocode listings,
  eighteen real outputs, and the paper's own architecture/execution-flow prose —
  are mirrored byte-exact in [`../docs/CORPUS-EXTRACTION.md`](../docs/CORPUS-EXTRACTION.md)
  (Appendices A–D). That mirror is what the fidelity tests read, so nothing was
  lost to the test suite.
- **The requirement ledger** derived from the tree lives in
  [`../docs/PARITY.md`](../docs/PARITY.md) (machine-checked in CI) and the audit
  records in [`../docs/CORPUS-EXTRACTION.md`](../docs/CORPUS-EXTRACTION.md) and
  `../docs/CORPUS-STATUS.md`.

## Recovering the raw tree

Everything tracked is recoverable from git history:

```bash
git log --diff-filter=D --name-only -- references/core   # find the removing commit
git checkout <commit>^ -- references/core                # restore the tree
```

The one exception is `media/live-footage/*.mp4`, which was always gitignored and
never tracked; the frames cited from it are committed under
`../docs/assets/live-footage/`.
