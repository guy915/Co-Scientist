"""Live PubMed/OpenAlex/INDRA contract + rate-limit smoke (N34).

``engine/mcp_server``'s own test suite fakes every HTTP client (see
``mcp_server/tests/test_openalex.py``'s docstring) -- correctly, since that
suite runs in hermetic CI (no external network, no API keys, no retries;
see ``docs/CI.md``). But a fake client can only ever agree with the
assumption it was written against; it cannot notice that NCBI or OpenAlex
changed a response field, tightened a rate limit, or started requiring a
parameter this project's parsers don't send. This module is the live
counterpart: it calls the real, public APIs directly and checks the
response shape the mcp_server tools actually parse (see
``tools/lit_review/search_pubmed.py``, ``tools/lit_review/openalex_search.py``,
``tools/indra_cogex/client.py``) still looks like what they expect.

**Deliberately not wired into CI** -- same reasoning as ``prod_smoke.py``:
live network, no key, subject to a public service's own rate limiting, so a
transient failure here is a finding to look at by hand, not a merge-blocking
flake. Run it directly:

    python -m evaluations.mcp_live_smoke

All three services are called read-only (GET/POST-as-query, nothing that
mutates their data) with a single small, cheap query each -- this is a
contract smoke, not a load test.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import httpx

_TIMEOUT_SECONDS = 30.0
# NCBI's documented per-IP ceiling without an API key (see
# entrez_rate_limit.py's own docstring): 3 requests/second.
_PUBMED_BURST_COUNT = 4
_PUBMED_BURST_INTERVAL_SECONDS = 0.1


@dataclass
class CheckResult:
    """Outcome of one live contract/rate-limit check."""

    name: str
    ok: bool
    info: str


def check_pubmed_contract() -> CheckResult:
    """A real E-utilities esearch call returns the shape the parser expects.

    Mirrors what `search_pubmed.py` -> `pubmed_client.py` ultimately reads
    off Entrez: an id list under `esearchresult.idlist`.
    """
    try:
        resp = httpx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": "CRISPR",
                "retmode": "json",
                "retmax": 3,
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return CheckResult("pubmed_contract", False, f"request failed: {exc}")
    if resp.status_code != 200:
        return CheckResult(
            "pubmed_contract", False, f"status {resp.status_code}"
        )
    id_list = resp.json().get("esearchresult", {}).get("idlist")
    ok = isinstance(id_list, list) and len(id_list) > 0
    return CheckResult(
        "pubmed_contract",
        ok,
        f"esearchresult.idlist has {id_list and len(id_list)} ids",
    )


def check_pubmed_burst_is_handled() -> CheckResult:
    """A burst faster than NCBI's documented ceiling never crashes the caller.

    Does not assert NCBI *must* throttle (that is NCBI's call, and it is
    often lenient) -- asserts every response in the burst is a well-formed
    HTTP response (200 or a clean 429/503), i.e. the kind of response
    `entrez_rate_limit.py`'s backoff is built to handle, never a raised
    transport exception this smoke has to catch as a failure.
    """
    statuses: list[int] = []
    try:
        for _ in range(_PUBMED_BURST_COUNT):
            resp = httpx.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={"db": "pubmed", "term": "cancer", "retmode": "json"},
                timeout=_TIMEOUT_SECONDS,
            )
            statuses.append(resp.status_code)
            time.sleep(_PUBMED_BURST_INTERVAL_SECONDS)
    except httpx.HTTPError as exc:
        return CheckResult(
            "pubmed_burst_handled", False, f"request failed: {exc}"
        )
    ok = all(code in (200, 429, 503) for code in statuses)
    return CheckResult(
        "pubmed_burst_handled", ok, f"burst of {len(statuses)}: {statuses}"
    )


def check_openalex_contract() -> CheckResult:
    """A real OpenAlex search returns the fields `openalex_search.py` reads.

    The tool derives title/authors/year/abstract/url per result; this
    checks the two fields with no forgiving fallback in the parser --
    `id` and the paginated `results` list itself.
    """
    try:
        resp = httpx.get(
            "https://api.openalex.org/works",
            params={"search": "CRISPR", "per_page": 1},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return CheckResult("openalex_contract", False, f"request failed: {exc}")
    if resp.status_code != 200:
        return CheckResult(
            "openalex_contract", False, f"status {resp.status_code}"
        )
    body = resp.json()
    results = body.get("results")
    ok = (
        isinstance(results, list)
        and len(results) > 0
        and isinstance(results[0].get("id"), str)
    )
    return CheckResult(
        "openalex_contract",
        ok,
        f"results[0].id={results and results[0].get('id')!r}",
    )


def check_indra_contract() -> CheckResult:
    """A real INDRA CoGex query returns the shape `client.py` expects.

    `get_genes_for_disease` returns a list of CoGex node dicts, each with a
    `data.db_ns`/`data.db_id` pair -- the fields the INDRA tools
    read off every result.
    """
    try:
        resp = httpx.post(
            "https://discovery.indra.bio/api/get_genes_for_disease",
            json={"disease": ["MESH", "D000544"]},  # Alzheimer disease.
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return CheckResult("indra_contract", False, f"request failed: {exc}")
    if resp.status_code != 200:
        return CheckResult(
            "indra_contract", False, f"status {resp.status_code}"
        )
    items = resp.json()
    ok = (
        isinstance(items, list)
        and len(items) > 0
        and "db_ns" in items[0].get("data", {})
    )
    return CheckResult("indra_contract", ok, f"{len(items)} gene(s) returned")


_CHECKS = (
    check_pubmed_contract,
    check_pubmed_burst_is_handled,
    check_openalex_contract,
    check_indra_contract,
)


def run() -> list[CheckResult]:
    """Runs every live check and returns their results."""
    return [check() for check in _CHECKS]


def main() -> int:
    """CLI entry point: run every check, print a report, return an exit code."""
    results = run()
    for result in results:
        marker = "OK  " if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {result.info}")
    ok = all(result.ok for result in results)
    print("mcp_live_smoke: OK" if ok else "mcp_live_smoke: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
