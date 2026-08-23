"""Tests for the ClinicalTrials.gov registry search."""

import httpx
import pytest
from mcp_server.tests._httpx import stub_failure, stub_responses
from mcp_server.tools import clinical_trials


def _study(**overrides: object) -> dict[str, object]:
    """Builds one v2 study payload with the modules the tool reads."""
    status: dict[str, object] = {
        "overallStatus": "TERMINATED",
        "whyStopped": "Insufficient efficacy",
        "startDateStruct": {"date": "2015-03"},
    }
    status.update(overrides)
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT01827384",
                "briefTitle": "Adavosertib in TP53-mutant tumours",
            },
            "statusModule": status,
            "designModule": {
                "phases": ["PHASE2"],
                "enrollmentInfo": {"count": 208},
            },
            "conditionsModule": {"conditions": ["Solid Tumour"]},
            "armsInterventionsModule": {
                "interventions": [{"name": "Adavosertib"}]
            },
        }
    }


async def test_a_terminated_trial_reports_why_it_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry's value over the literature is the negative result.

    A trial that ran and failed is the strongest possible answer to "has
    anyone tried this", and it is the case least likely to have been
    written up -- which is exactly what makes a gap argued from papers
    alone unreliable.
    """
    stub_responses(monkeypatch, {"studies": [_study()]})

    result = await clinical_trials.search_clinical_trials("adavosertib")

    (record,) = result["records"]
    assert record["nct_id"] == "NCT01827384"
    assert record["status"] == "TERMINATED"
    assert record["why_stopped"] == "Insufficient efficacy"
    assert record["interventions"] == ["Adavosertib"]


async def test_a_study_missing_modules_is_ordinary_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registrations are incomplete all the time; that is not a failure."""
    stub_responses(
        monkeypatch,
        {"studies": [{"protocolSection": {"identificationModule": {}}}]},
    )

    result = await clinical_trials.search_clinical_trials("nothing")

    (record,) = result["records"]
    assert record["status"] is None
    assert record["interventions"] == []


async def test_a_failed_request_degrades_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One unreachable source must not fail a step consulting several."""
    stub_failure(monkeypatch, httpx.ConnectError("boom"))

    result = await clinical_trials.search_clinical_trials("adavosertib")

    assert result == {
        "source": "ClinicalTrials.gov",
        "query": "adavosertib",
        "records": [],
    }
