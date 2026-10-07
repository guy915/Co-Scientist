# ADR-002: Layering and how it is enforced

**Status:** accepted, 7 October 2026. Re-architecture phase 1.

## Context

Layering rules lived in prose (`AGENTS.md`) and in a few hand-written AST
tests (`app/tests/test_architecture.py`, `engine/tests/test_agents.py`).
Agents write most of this code, and a rule nobody checks decays. ADR-001 sets
the layers; this ADR sets the tool, the contracts and how violations shrink.

## Decision

**Tool: `import-linter`** (a dev dependency of the engine distribution). It
builds the graph with `grimp`, counts function-local and `TYPE_CHECKING`
imports like any other, and reports every broken contract with its import
chain.

**`make arch`** runs `lint-imports` against the root `.importlinter`
configuration, from `app/` so that `app` imports as the package rather than
the directory. `make lint` runs it, and CI runs it in the typecheck job, which
already installs the backend. It needs no network and no keys.

**Contracts:**

1. **Layers** over `co_scientist` and the not-yet-moved `app` modules, using
   ADR-001's map. Each layer names its target package as optional
   (`(co_scientist.api)`) plus the current modules that will move there, so
   the contract checks the real code today and keeps checking it as modules
   move. A move PR edits module names in the contract; it never adds an
   exception.
2. **Independence** of the science agents.
3. **Domain layering**: `chat` > `report` > `safety` > `research_state` >
   `documents` | `access` | `feedback`, as part of contract 1.
4. **Forbidden third parties**: `fastapi`/`starlette` outside `api` and
   `main`; `litellm` outside `platform/llm`; `httpx` outside `platform/llm`
   and `platform/retrieval`; `sqlite3` outside `platform/db`, the domains and
   `orchestration`.
5. **Acyclic siblings** within `co_scientist`, so the "0 cycles" target is
   checked rather than measured once. Added after phase 4: its cycle breakers
   are chosen per parent package, so they change as modules move, which a
   shrink-only list cannot absorb. Until then contract 1 forbids every cycle
   that crosses a layer.

Sibling groups that are not yet single packages (`documents` | `access` |
`feedback`; `llm` | `sandbox` | `db`) share one layer until they move; an
import-linter layer can only declare whole modules independent. Their
independence contracts are added when the packages exist. Five imports
cross those groups today and are fixed before then:
`provider_usage → store.db`, `retention → store.documents`,
`llm.tools.transcript → workspace.tool_schemas` and
`workspace.{session,tools} → tool_effects`.

Package `__init__` modules whose children belong to different layers
(`app.engine_adapter`, `app.engine_adapter.drain`, `co_scientist.agents`,
`co_scientist.config`, `co_scientist.models`) cannot be named in a layer
without their children. They join their layer when they move; the ignore
list already holds the imports that reach through them.

**Every current violation is an `ignore_imports` entry**, grouped under the
contract it breaks. import-linter fails on an entry that no longer matches,
so a fix must delete its entry. A structural test in `evaluations/tests/`
counts the entries and compares the count with a ceiling written in the
test: more entries fail, and so do fewer, until the ceiling is lowered in the
same PR. The list can only shrink. The campaign ends with an empty list and
the test asserting zero.

The six engine directories without `__init__.py` (`llm/request`,
`llm/attempts`, `llm/tools`, `llm/admission`, `llm/structured`, `offline`)
get empty ones first; grimp cannot see namespace packages, and 15 modules
would otherwise be outside every contract.

The existing AST tests stay until a contract covers what they check. The
"engine does not depend on app" test is replaced by contract 1, because moved
modules import not-yet-moved ones across the old boundary while the layer
rule still holds. `engine/tests/test_agents.py`'s ordering of the
`co_scientist.llm` subpackages stays as a finer rule inside one adapter.

## Consequences

- A prose rule that a contract enforces is deleted from `AGENTS.md` in phase 8
  and replaced by a pointer to `make arch`.
- Lazy imports no longer hide cycles: the 23- and 11-module cycles closed by
  function-local imports appear as ignore entries until phase 5 removes them.
- Adding a layer-crossing import shows up as a red `make arch` with the import
  chain, not as a review comment.
- The contracts do not check the "import only from `__init__`" rule. Phase 5
  adds it per package as each interface settles (a forbidden contract on the
  package's submodules, or a protected contract).
