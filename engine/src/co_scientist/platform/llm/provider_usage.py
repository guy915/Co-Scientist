from typing import Any, NoReturn

from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.platform.llm.admission.service import reserve_physical as reserve_physical
from co_scientist.platform.llm.admission.service import scoped_client as scoped_client


def raise_http_admission(error: ProviderAdmissionError) -> NoReturn:
    # Engine-only installations do not depend on FastAPI.
    from fastapi import HTTPException

    raise HTTPException(status_code=429, detail=str(error)) from error


def reserve(request: dict[str, Any]) -> None:
    try:
        reserve_physical(request, app=True)
    except ProviderAdmissionError as error:
        raise_http_admission(error)
