"""ClinicalTrials.gov search: what has actually been tried in people.

The question this answers is the one a literature search answers badly.
A gap argued from papers is a gap in what somebody wrote up; a registry
records the trials that ran, including the ones that were terminated and
never published, which is exactly the evidence a "nobody has tried this"
claim needs and exactly the evidence publication bias removes.

Degrades to an empty-records envelope rather than raising, like every
other tool on the enrichment and reflection paths.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"


def _empty_result(query: str) -> dict[str, Any]:
    """Builds the envelope a search returns when it cannot answer."""
    return {"source": "ClinicalTrials.gov", "query": query, "records": []}


def _record(study: dict[str, Any]) -> dict[str, Any]:
    """Normalizes one v2 study into a flat record.

    The v2 payload nests everything under protocolSection modules, and a
    study missing a module is ordinary rather than exceptional, so every
    lookup tolerates absence.
    """
    protocol = study.get("protocolSection") or {}
    identification = protocol.get("identificationModule") or {}
    status = protocol.get("statusModule") or {}
    design = protocol.get("designModule") or {}
    conditions = protocol.get("conditionsModule") or {}
    arms = protocol.get("armsInterventionsModule") or {}
    nct_id = identification.get("nctId")
    return {
        "nct_id": nct_id,
        "title": identification.get("briefTitle"),
        # Status carries the finding a paper never reports: a terminated
        # or withdrawn trial is evidence about the approach, and it is
        # the case least likely to have been published.
        "status": status.get("overallStatus"),
        "why_stopped": status.get("whyStopped"),
        "phases": design.get("phases"),
        "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
        "conditions": conditions.get("conditions"),
        "interventions": [
            intervention.get("name")
            for intervention in (arms.get("interventions") or [])
            if isinstance(intervention, dict)
        ],
        "start_date": (status.get("startDateStruct") or {}).get("date"),
        "url": f"https://clinicaltrials.gov/study/{nct_id}",
    }


async def search_clinical_trials(
    query: str, max_results: int = 10
) -> dict[str, Any]:
    """Search registered clinical trials by intervention, condition or term.

    Args:
        query: An intervention, condition, or free-text search term.
        max_results: Maximum studies to return, capped at 25.

    Returns:
        Source-stamped trial records carrying status and, where a trial
        stopped early, why -- or an empty-records envelope.
    """
    limit = max(1, min(max_results, 25))
    params: dict[str, str | int] = {
        "query.term": query,
        "pageSize": limit,
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(_TRIALS_URL, params=params)
            response.raise_for_status()
        studies = (response.json().get("studies") or [])[:limit]
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "ClinicalTrials.gov search failed for %r: %s", query, exc
        )
        return _empty_result(query)
    return {
        "source": "ClinicalTrials.gov",
        "query": query,
        "records": [_record(study) for study in studies],
    }
