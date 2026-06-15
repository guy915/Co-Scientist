# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Shared client for INDRA CoGex REST API.

All INDRA CoGex endpoints are POST with JSON body payloads.
Entity identifiers use a 2-element tuple format: [namespace, id].
"""

import os
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

INDRA_BASE_URL = os.getenv("INDRA_COGEX_URL", "https://discovery.indra.bio")
INDRA_TIMEOUT = float(os.getenv("INDRA_COGEX_TIMEOUT", "120"))


def parse_id(identifier: str) -> list[str]:
    """Parses 'NAMESPACE:id' into [namespace, id] for the INDRA API.

    Examples:
        "HGNC:6407" -> ["HGNC", "6407"]
        "MESH:D002289" -> ["MESH", "D002289"]
        "CHEBI:CHEBI:27690" -> ["CHEBI", "CHEBI:27690"]

    Args:
        identifier: Entity identifier string in NAMESPACE:id format.

    Returns:
        Two-element list [namespace, id].

    Raises:
        ValueError: If the identifier is not in a valid NAMESPACE:id format.
    """
    parts = identifier.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"invalid identifier: '{identifier}'. "
                         f"expected 'NAMESPACE:id' (e.g. 'HGNC:6407')")
    return parts


def maybe_parse_agent(value: str) -> str | list[str]:
    """Parses value as CURIE tuple if it contains ':', otherwise returns as-is.

    The INDRA get_statements endpoint accepts both plain names ("KRAS")
    and CURIE tuples (["HGNC", "6407"]).

    Args:
        value: Agent name or CURIE string.

    Returns:
        A two-element list [namespace, id] if parseable as CURIE, else the
        original string.
    """
    if ":" in value and not value.startswith("http"):
        try:
            return parse_id(value)
        except ValueError:
            return value
    return value


async def indra_post(endpoint: str, payload: dict[str, Any]) -> Any:
    """POSTs to the INDRA CoGex API and returns parsed JSON.

    Args:
        endpoint: API path, e.g. "/api/get_genes_for_disease".
        payload: JSON-serializable request body.

    Returns:
        Parsed JSON response from the API.
    """
    url = f"{INDRA_BASE_URL}{endpoint}"
    logger.debug("indra request: %s", endpoint)
    async with httpx.AsyncClient(timeout=INDRA_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


def cap_results(items: list[Any] | Any, limit: int) -> tuple[list[Any], int]:
    """Caps a list at limit and returns (capped_list, original_count).

    Args:
        items: List to cap, or any non-list value.
        limit: Maximum number of items to return.

    Returns:
        Tuple of (capped list, original total count). If items is not a list,
        returns (items, 0).
    """
    if not isinstance(items, list):
        return items, 0
    total = len(items)
    return items[:limit], total
