# Dependency advisory review

Production locks record reviewed Python versions and hashes. Frozen Bun locks
record the frontend and browser harness closure. Audit those closures against
current advisory data as well as running implementation tests. An audit is
an online maintenance operation, separate from the offline `make check`.

```bash
make audit-deps
```

This requires uv, Bun 1.3.14 and Node.js 22.13+. It audits all three Python
locks with pip-audit 2.10.1, then the frontend and browser harness with Bun.
It returns nonzero if any audit fails or reports advisory matches. It does
not install project dependencies, execute project code, suppress findings,
or automatically upgrade packages. Review reachability before changing a
framework major or discarding a compatibility bound.

## 1 October 2026 results

The frontend and browser harness audits reported no known vulnerabilities
after refreshing the frozen closures. React Router, Vite, Vitest, and their
transitive tooling updates stay within the existing major versions. The old
Browserslist override was removed. GTS's legacy `external-editor` dependency
requires an obsolete `tmp` range, so `tmp` is explicitly overridden to 0.2.7;
its temporary-file creation and cleanup API was checked for compatibility.

Python updates raised LangChain Core to 1.3.3, MCP's FastAPI to 0.142.2,
Starlette to 1.7.0, lxml to 6.1.3, and pypdf to 6.19.0. Metadata now requires
the applicable patched release floors. The app and MCP authorization checks
use the routed ASGI path; they do not derive the security decision from a
URL reconstructed with a caller-supplied Host header. A crafted Host bypass
was reproduced against the earlier MCP dependency and middleware combination,
and regression tests cover denial and researcher ownership.

The remaining Python detector findings were reviewed against the deployed
application shape. They remain visible in raw audit output:

| Package | Remaining findings | Reachability assessment |
| --- | --- | --- |
| LiteLLM 1.80.17 | 23 distinct advisory IDs covering proxy management, authentication, guardrails, MCP proxy and provider-routing endpoints | This application imports the completion SDK, which indirectly imports proxy CLI code. The application does not mount or launch the vulnerable proxy HTTP service or configure enterprise guardrails. Those reported HTTP surfaces are absent. Preserve the existing SDK compatibility range until a deliberate SDK upgrade is validated, including free-route wire behavior and spend bounds. |
| FastMCP 2.14.7 | PYSEC-2026-2475, PYSEC-2026-2476 | The first affects Windows CLI installation with shell metacharacters in server names; production is Linux and does not run those install commands. The second affects OAuthProxy consent flows; this server uses its own shared-secret middleware and does not configure FastMCP OAuth providers. |
| DiskCache 5.6.3 | PYSEC-2026-2447 | Pickle deserialization requires attacker write access to an active DiskCache directory. This package is transitive through FastMCP's optional disk-backed key/value store; the application's MCP server does not instantiate that store or its OAuth providers. The literature cache stores papers rather than DiskCache pickles. |

The isolated science-skills dependency closure had no advisory matches.
Counts are deduplicated by advisory ID; raw PyPI results can repeat an entry
through multiple advisory aliases.

These are scoped reachability assessments, not permanent waivers. Revisit
them when dependency versions, authentication providers, cache backends,
operating systems, service entrypoints, or proxy topology change. Running a
LiteLLM proxy or adding FastMCP OAuth changes these assessments and requires
patched versions first. A new advisory must receive its own assessment.

The audit does not inspect operating-system packages in a built container.
Container builds and a review of the actual deployed image remain separate
release checks. See [LAUNCH.md](LAUNCH.md) and
[PUBLICATION-REVIEW.md](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/PUBLICATION-REVIEW.md).

## 2 October 2026 refresh

All five locked closures were audited again on `af656a91`. Every scanner
completed; the audit target returned nonzero because Python advisories remain,
not because scanning failed. Package versions and distinct counts match the
previous record: 23 LiteLLM IDs, two FastMCP IDs and one DiskCache ID. The
skills, frontend and browser-harness closures reported no advisory matches.
The [dated snapshot](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/decisions/2026-10-02-dependency-audit.json) records the
current IDs, detector-listed fixes and the hashes of the audited locks; the
previous prose record does not establish an exact historical ID-set match.

The shared app/engine completion transport still uses the SDK backend and adds
no proxy HTTP routes. Railway's rendered production MCP variable-name inventory
contains no `FASTMCP_SERVER_AUTH` override. Values are withheld by the connector;
this check establishes the absence of that configured override, not an audit of
all live runtime state or container OS packages.

No newly reachable reported surface was identified. Dependency upgrades remain
separate compatibility work: the detector-listed FastMCP fixes require 3.2.0,
LiteLLM fixes exceed the current SDK bound and do not establish a fully clean
target, and DiskCache lists no fixed release. The findings remain visible;
dependency versions, bounds and locks are unchanged by this refresh.
