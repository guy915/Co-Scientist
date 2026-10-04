"""Read-only live contracts stay outside hermetic CI; transient service
failures require manual review.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import httpx

_TIMEOUT_SECONDS = 30.0
# NCBI's unkeyed per-IP ceiling is 3 requests/s.
_PUBMED_BURST_COUNT = 4
_PUBMED_BURST_INTERVAL_SECONDS = 0.1


@dataclass
class CheckResult:
    name: str
    ok: bool
    info: str


def check_pubmed_contract() -> CheckResult:
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
    """NCBI may allow a burst; require well-formed responses, not proof that
    it must throttle.
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
    try:
        resp = httpx.post(
            "https://discovery.indra.bio/api/get_genes_for_disease",
            json={"disease": ["MESH", "D000544"]},
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
    return [check() for check in _CHECKS]


def main() -> int:
    results = run()
    for result in results:
        marker = "OK  " if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {result.info}")
    ok = all(result.ok for result in results)
    print("mcp_live_smoke: OK" if ok else "mcp_live_smoke: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
