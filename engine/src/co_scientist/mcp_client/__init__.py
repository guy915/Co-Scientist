"""HTTP MCP sessions, availability probes, campaign auth and bounded tool calls.

MCPToolClient is the public client. Shared accessors retain event-loop-scoped
connections and availability state.
"""

import asyncio
import copy
import json
import logging
import os
import threading
import weakref
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import urlsplit, urlunsplit

import httpx
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection

from co_scientist.config.env_vars import parse_timeout_env
from co_scientist.constants import truncate
from co_scientist.exceptions import MCPToolTimeoutError
from co_scientist.llm import campaign_free_mode

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


def _resolve_availability_check_tool(
    tool_registry: Optional["ToolRegistry"],
) -> tuple[str | None, bool]:
    """Determine which MCP tool (if any) to use for an availability probe.

    Args:
        tool_registry: Optional ToolRegistry for config-driven tool lookup.

    Returns:
        A (check_tool_name, skip_availability_check) pair. When
        skip_availability_check is True, the caller should treat the source
        as available once the MCP server itself responds, without invoking
        any tool. check_tool_name defaults to "check_pubmed_available" for
        backwards compatibility when no registry is supplied.
    """
    if tool_registry is None:
        # Default for backwards compat when no registry is supplied.
        return "check_pubmed_available", False

    workflow = tool_registry.get_workflow("literature_review")
    if not workflow:
        return None, False

    if not workflow.availability_check:
        # availability_check is null/None - skip the check
        logger.debug(
            "availability check disabled in config (availability_check: null)"
        )
        return None, True

    # Explicit check tool configured.
    tool_config = tool_registry.get_tool(workflow.availability_check)
    check_tool_name = tool_config.mcp_tool_name if tool_config else None
    return check_tool_name, False


def _interpret_availability_result(result: Any, check_tool_name: str) -> bool:
    """Coerce an availability-check tool's raw result to a bool.

    Args:
        result: Raw MCP tool result. The tool contract is a bool or a
            "true"/"false" string; anything else is unexpected.
        check_tool_name: Name of the tool that produced the result, used
            only for the unexpected-shape warning.

    Returns:
        True/False per the tool's answer; False if the shape is unexpected.
    """
    if isinstance(result, bool):
        return result
    if isinstance(result, str):
        return result.lower() == "true"
    logger.warning("unexpected result from %s: %s", check_tool_name, result)
    return False


def _short_circuit_availability(
    all_tools_dict: dict[str, Any],
    check_tool_name: str | None,
    skip_availability_check: bool,
) -> bool | None:
    """Resolves availability without calling any tool, when possible.

    Checks, in order: no tools at all (unavailable), the workflow config
    opts out of a source-specific check, or no check tool is configured
    (both available since the server itself responded). Returns None when
    none apply, meaning the caller must actually invoke check_tool_name.

    Args:
        all_tools_dict: Tools available on the already-initialized client.
        check_tool_name: Availability-check tool name, or None if none is
            configured.
        skip_availability_check: Whether the server responding is enough,
            without calling a tool.

    Returns:
        True/False if availability is already decided, else None.
    """
    if not all_tools_dict:
        logger.warning(
            "MCP server responded but provided no tools,"
            " literature source unavailable"
        )
        return False

    if skip_availability_check or check_tool_name is None:
        logger.info(
            "MCP server available, skipping source-specific availability check"
            if skip_availability_check
            else "no availability check tool configured, assuming source"
            " available"
        )
        return True

    return None


async def _call_check_tool(
    mcp_client: "MCPToolClient",
    check_tool_name: str | None,
    all_tools_dict: dict[str, Any],
) -> bool:
    """Calls check_tool_name and interprets its result, if it exists.

    Args:
        mcp_client: An initialized MCPToolClient to call the tool on.
        check_tool_name: Name of the availability-check tool to call.
        all_tools_dict: Tools available on the already-initialized client.

    Returns:
        True/False per the tool's answer, or False if the tool is absent.
    """
    if check_tool_name not in all_tools_dict:
        logger.warning(
            "availability check tool '%s' not found. available tools: %s",
            check_tool_name,
            list(all_tools_dict.keys()),
        )
        return False

    logger.debug("%s tool found, executing", check_tool_name)
    # Result should be a boolean or "true"/"false" string.
    result = await mcp_client.call_tool(check_tool_name)
    return _interpret_availability_result(result, check_tool_name)


async def _probe_literature_source_availability(
    mcp_client: "MCPToolClient",
    check_tool_name: str | None,
    skip_availability_check: bool,
) -> bool:
    """Determine availability from an already-initialized MCP client.

    Args:
        mcp_client: An initialized MCPToolClient to query for tools and, if
            needed, to call the availability check tool on.
        check_tool_name: Name of the availability-check tool to call, or
            None if no such tool is configured.
        skip_availability_check: When True, the source is treated as
            available once the MCP server itself responds, without calling
            a tool.

    Returns:
        True if the literature source is available via MCP server, False
        otherwise.
    """
    all_tools_dict, _ = mcp_client.get_tools()

    shortcut = _short_circuit_availability(
        all_tools_dict, check_tool_name, skip_availability_check
    )
    if shortcut is not None:
        return shortcut

    logger.debug(
        "checking literature source availability (tool: %s)", check_tool_name
    )
    logger.debug("available mcp tools: %s", list(all_tools_dict.keys()))

    return await _call_check_tool(mcp_client, check_tool_name, all_tools_dict)


def _log_mcp_test_start(
    tool_registry: Optional["ToolRegistry"], server_url: str | None
) -> None:
    """Logs which MCP target check_mcp_available is about to probe.

    Args:
        tool_registry: ToolRegistry driving multi-server mode, if any.
        server_url: Single legacy server URL, used when tool_registry isn't.
    """
    if tool_registry:
        logger.debug(
            "testing mcp availability for %s server(s)",
            len(tool_registry.get_enabled_servers()),
        )
    else:
        logger.debug("testing mcp server availability at %s", server_url)


def _has_any_tools(tools_dict: dict[str, Any] | None) -> bool:
    """Checks whether an initialized client actually reports any tools.

    Args:
        tools_dict: The probe client's populated tools dict.

    Returns:
        True (and logs success) if non-empty; False (and logs a warning)
        otherwise.
    """
    if tools_dict and len(tools_dict) > 0:
        logger.info("MCP server available with %s tools", len(tools_dict))
        return True
    logger.warning("MCP server responded but provided no tools")
    return False


def _log_mcp_unavailable(
    tool_registry: Optional["ToolRegistry"],
    server_url: str | None,
    error: Exception,
) -> None:
    """Logs the check_mcp_available exception-fallback-to-False path.

    Args:
        tool_registry: ToolRegistry driving multi-server mode, if any.
        server_url: Single legacy server URL, used when tool_registry isn't.
        error: The exception that triggered the fallback.
    """
    if tool_registry:
        logger.warning("MCP servers unavailable: %s", error)
    else:
        logger.warning("MCP server unavailable at %s", server_url)


if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


DEFAULT_MCP_SERVER_URL = "http://localhost:8888/mcp"
"""Fallback MCP server URL when MCP_SERVER_URL is unset."""

MCP_SHARED_SECRET_ENV = "COSCIENTIST_MCP_SHARED_SECRET"
"""Env var carrying the shared-secret token sent with every MCP call.

Set identically on the api and mcp services (see AGENTS.md's deployment
section) so the reference MCP server can require it instead of trusting
network placement alone. Left unset on either side reproduces the prior
behaviour exactly -- no header is sent, and the server does not require one
-- so introducing this cannot break a deployment that has not set it yet.
"""

MCP_AUTH_HEADER = "X-MCP-Shared-Secret"
"""HTTP header name carrying the shared secret, checked by the MCP server."""

MCP_CAMPAIGN_HEADER = "X-CoScientist-Campaign"
"""Authenticated request marker enabling campaign MCP policy."""


def _resolve_server_url() -> str:
    """Return the MCP server URL from the environment or the default."""
    return os.environ.get("MCP_SERVER_URL", DEFAULT_MCP_SERVER_URL)


def _mcp_auth_headers() -> dict[str, Any] | None:
    """Return the shared-secret header this client should send, if any.

    Returns:
        A single-entry headers dict when ``COSCIENTIST_MCP_SHARED_SECRET``
        is set, else None -- so callers can omit the "headers" key entirely
        rather than sending an empty one.
    """
    secret = os.environ.get(MCP_SHARED_SECRET_ENV)
    if not secret:
        return None
    headers = {MCP_AUTH_HEADER: secret}
    from co_scientist.llm import campaign_free_mode

    if campaign_free_mode():
        headers[MCP_CAMPAIGN_HEADER] = "1"
    return headers


def _with_shared_secret(
    configs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Attach the shared-secret header to every resolved server config.

    Applied once here, after the config is resolved, so every path into
    MCPToolClient -- registry-driven, explicit configs, or the legacy
    single-URL fallback -- sends the same header without each branch having
    to remember to.

    Args:
        configs: Server configs as {server_id: {"transport": ..., "url":
            ...}}.

    Returns:
        The same configs, each carrying a merged "headers" entry, when a
        shared secret is configured; unchanged otherwise.
    """
    headers = _mcp_auth_headers()
    if headers is None:
        return configs
    return {
        server_id: {
            **cfg,
            "headers": {**(cfg.get("headers") or {}), **headers},
        }
        for server_id, cfg in configs.items()
    }


def _resolve_server_configs(
    tool_registry: Optional["ToolRegistry"],
    server_configs: dict[str, dict[str, Any]] | None,
    server_url: str | None,
) -> dict[str, dict[str, Any]]:
    """Resolve which MCP server configs MCPToolClient.__init__ should use.

    Precedence: an explicit tool_registry wins, then explicit
    server_configs, then a single legacy server_url (falling back to the
    env var / default). Every path is given the shared-secret header before
    returning, when one is configured.

    Args:
        tool_registry: ToolRegistry instance for config-driven multi-server
            mode, if provided.
        server_configs: Dict of server configs for multi-server mode, if
            provided.
        server_url: URL of a single MCP server (legacy mode), if provided.

    Returns:
        Dict of {server_id: {"transport": ..., "url": ..., "headers": ...}}.
    """
    if tool_registry is not None:
        # Use registry-provided server configs
        configs = tool_registry.get_server_configs_for_langchain()
        logger.debug("using %s servers from tool registry", len(configs))
        return _with_shared_secret(configs)

    if server_configs is not None:
        logger.debug("using %s provided server configs", len(server_configs))
        return _with_shared_secret(server_configs)

    # Legacy single-server mode
    if server_url is None:
        server_url = _resolve_server_url()
    logger.debug("using single server: %s", server_url)
    return _with_shared_secret(
        {"default": {"transport": "streamable_http", "url": server_url}}
    )


NOT_INITIALIZED_MESSAGE = "mcp client not initialized. call initialize() first."
"""Single wording for every "initialize() has not run" guard on the client.

Each guard raising its own literal is how the wording drifted before (one
copy was capitalized differently), so they all read it from here.
"""


def _ensure_tools_initialized(
    tools_dict: dict[str, Any] | None,
) -> dict[str, Any]:
    """Guards that a client's tools dict has been populated by initialize().

    Args:
        tools_dict: A client's ``_tools_dict``, or None if initialize()
            hasn't run.

    Returns:
        The non-None tools dict.

    Raises:
        RuntimeError: If tools_dict is None.
    """
    if tools_dict is None:
        raise RuntimeError(NOT_INITIALIZED_MESSAGE)
    return tools_dict


def _is_wrapped_text_result(result: Any) -> bool:
    """Checks whether result is the ``[{"text": ...}]`` wrapper shape.

    Some langchain versions wrap MCP tool results this way instead of
    returning the raw string.

    Args:
        result: Raw ``ainvoke()`` return value.

    Returns:
        True if result is a non-empty list whose first item is a dict
        containing a "text" key.
    """
    return (
        isinstance(result, list)
        and len(result) > 0
        and isinstance(result[0], dict)
        and "text" in result[0]
    )


def _unwrap_tool_result(result: Any) -> Any:
    """Unwraps the ``[{"text": ...}]`` shape some langchain versions return.

    Args:
        result: Raw ``ainvoke()`` return value.

    Returns:
        ``result[0]["text"]`` when result matches that shape, else result
        unchanged.
    """
    return result[0]["text"] if _is_wrapped_text_result(result) else result


def _filter_tools_by_whitelist(
    tools_dict: dict[str, Any],
    whitelist: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Filters a client's tools down to a workflow's whitelist.

    Args:
        tools_dict: All available tools, keyed by name.
        whitelist: Tool names to keep, in the order the LLM should see them.

    Returns:
        Tuple of (filtered_tools_dict, filtered_openai_tools). The latter
        follows whitelist order (not tools_dict's order) so the OpenAI-format
        tool list is presented to the LLM in the order the workflow config
        declared it, e.g. preferred tools first.
    """
    filtered_tools_dict = {
        k: v for k, v in tools_dict.items() if k in whitelist
    }
    filtered_openai_tools = [
        convert_to_openai_tool(filtered_tools_dict[k])
        for k in whitelist
        if k in filtered_tools_dict
    ]

    logger.debug(
        "filtered to %s tools: %s",
        len(filtered_tools_dict),
        list(filtered_tools_dict.keys()),
    )

    return filtered_tools_dict, filtered_openai_tools


POLICY = "coscientist-public-retrieval-v1"
# Protocol surface implemented by the independently packaged reference server.
PUBLIC_TOOLS = frozenset(
    {
        "check_pubmed_available",
        "search_pubmed",
        "pubmed_search_with_fulltext",
        "search_openalex",
        "get_opencitations_citation_edges",
        "search_chembl",
        "search_uniprot",
        "search_string_interactions",
        "search_reactome_pathways",
        "search_open_targets",
        "search_europepmc",
        "search_preprints",
        "search_arxiv",
        "search_biorxiv",
        "search_ensembl_gene",
        "search_gnomad_constraint",
        "search_clinical_trials",
        "search_gwas_catalog_associations",
    }
)
_M10_PUBLIC_TOOLS = PUBLIC_TOOLS - {"search_gwas_catalog_associations"}
_PRE_CITATION_ROLLBACK_TOOLS = _M10_PUBLIC_TOOLS - {
    "get_opencitations_citation_edges"
}


class CampaignToolUnavailableError(RuntimeError):
    """A tool outside the campaign policy was asked for.

    Permanent for the whole run: the policy is fixed while the campaign
    scope is active, so retrying the call cannot admit it.
    """


def campaign_serves_tool(name: str) -> bool:
    """Whether the current scope may call MCP tool ``name`` at all.

    Outside campaign mode every tool may be called. Inside it only the
    reviewed public tools are admitted, so a caller can skip the rest
    instead of issuing a call that is refused every time.
    """
    return not campaign_free_mode() or name in PUBLIC_TOOLS


def _qualified_url(configs: dict[str, dict[str, Any]]) -> str:
    expected = os.getenv("COSCIENTIST_CAMPAIGN_MCP_URL", "")
    if not expected or len(configs) != 1:
        raise RuntimeError(
            "campaign MCP requires one explicitly qualified endpoint"
        )
    config = next(iter(configs.values()))
    secret = os.getenv(MCP_SHARED_SECRET_ENV)
    if not secret:
        raise RuntimeError("campaign MCP requires shared-secret authentication")
    headers = {
        MCP_AUTH_HEADER: secret,
        MCP_CAMPAIGN_HEADER: "1",
    }
    if (
        set(config) - {"transport", "url", "headers"}
        or config.get("transport") != "streamable_http"
        or config.get("url") != expected
        or (config.get("headers") or {}) != headers
    ):
        raise RuntimeError("campaign MCP configuration is not qualified")
    url = urlsplit(expected)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path != "/mcp"
    ):
        raise RuntimeError("campaign MCP endpoint must be a plain /mcp URL")
    return expected


def campaign_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    follow_redirects: bool = False,
) -> httpx.AsyncClient:
    """Prevent redirects and proxies from changing the qualified route."""
    del follow_redirects
    if auth is not None:
        raise RuntimeError("campaign MCP custom authentication is unavailable")
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout or httpx.Timeout(30),
        follow_redirects=False,
        trust_env=False,
    )


class CampaignAdmission:
    """Bind tools to one configuration and recheck its serving policy."""

    def __init__(self, configs: dict[str, dict[str, Any]]) -> None:
        """Snapshot the qualified configuration before discovery."""
        self.configs = copy.deepcopy(configs)
        self.url = _qualified_url(configs)

    async def verify(self, configs: dict[str, dict[str, Any]]) -> None:
        """Require the bound route and a current reference-server policy."""
        if configs != self.configs or _qualified_url(configs) != self.url:
            raise RuntimeError(
                "campaign MCP binding changed; initialize a new client"
            )
        url = urlsplit(self.url)
        root = urlunsplit((url.scheme, url.netloc, "/", "", ""))
        headers = next(iter(self.configs.values())).get("headers")
        async with campaign_http_client(headers=headers) as client:
            response = await client.get(root)
            response.raise_for_status()
            data = response.json()
        expected_policy = {
            "version": POLICY,
            "enabled": True,
            "anonymous_openalex": True,
        }
        # M10 added citation edges; M11 added GWAS after it. Accept those
        # exact rollout states plus the known pre-citation rollback target.
        # Reject hybrids and every unreviewed tool addition.
        accepted_policies = [
            {**expected_policy, "tools": sorted(tools)}
            for tools in (
                PUBLIC_TOOLS,
                _M10_PUBLIC_TOOLS,
                _PRE_CITATION_ROLLBACK_TOOLS,
            )
        ]
        if (
            not isinstance(data, dict)
            or data.get("campaign_policy") not in accepted_policies
            or data.get("service") != "coscientist-lit-review"
        ):
            raise RuntimeError(
                "campaign MCP server policy is unavailable or unqualified"
            )

    async def require_tool(
        self, name: str, configs: dict[str, dict[str, Any]]
    ) -> None:
        """Admit only reviewed tools on the qualified serving deployment."""
        if name not in PUBLIC_TOOLS:
            raise CampaignToolUnavailableError(
                "tool is unavailable under campaign MCP policy"
            )
        await self.verify(configs)

    def transport_configs(self) -> dict[str, dict[str, Any]]:
        """Use the fixed transport factory for the captured configuration."""
        return {
            name: {**config, "httpx_client_factory": campaign_http_client}
            for name, config in copy.deepcopy(self.configs).items()
        }


def require_bound_mode(admission: CampaignAdmission | None) -> None:
    """Reject clients discovered before campaign qualification."""
    if campaign_free_mode() and admission is None:
        raise RuntimeError(
            "campaign MCP client was not qualified at initialization"
        )


async def prepare_admission(
    configs: dict[str, dict[str, Any]],
) -> CampaignAdmission | None:
    """Qualify campaign transport before the MCP SDK opens a connection."""
    if not campaign_free_mode():
        return None
    admission = CampaignAdmission(configs)
    await admission.verify(configs)
    return admission


if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


MCP_TOOL_TIMEOUT_ENV = "COSCIENTIST_MCP_TOOL_TIMEOUT_SECONDS"
# Generous next to a search or a full-text fetch, tiny next to forever. The
# failure this bounds is not a slow tool but a dead one: an MCP stream that
# broke mid-call leaves the await pending with nothing to complete it.
DEFAULT_MCP_TOOL_TIMEOUT_SECONDS = 300.0


def mcp_tool_timeout_seconds() -> float | None:
    """Return the per-tool-call wall-clock ceiling, or None when disabled.

    Read from the environment on every call rather than cached, so tests and
    operators can change the ceiling without restarting the process. Mirrors
    ``llm.request.completion.llm_timeout_seconds``.

    Returns:
        The timeout in seconds, or None when it is disabled (a value of zero
        or less) or the configured value is not a number.
    """
    return parse_timeout_env(
        MCP_TOOL_TIMEOUT_ENV, DEFAULT_MCP_TOOL_TIMEOUT_SECONDS
    )


async def _ainvoke_within_timeout(
    tool: Any, tool_args: Any, tool_name: str
) -> Any:
    """Invoke one MCP tool under a wall-clock ceiling.

    Args:
        tool: The MCP tool object to invoke.
        tool_args: Arguments to pass to the tool.
        tool_name: Name of the tool, for the error message.

    Returns:
        Whatever the tool returned.

    Raises:
        MCPToolTimeoutError: If the call outlives the configured ceiling.
    """
    timeout = mcp_tool_timeout_seconds()
    if timeout is None:
        return await tool.ainvoke(tool_args)
    try:
        return await asyncio.wait_for(tool.ainvoke(tool_args), timeout=timeout)
    except asyncio.TimeoutError as exc:
        # wait_for has already cancelled the underlying call, so the broken
        # stream is not left holding the task.
        raise MCPToolTimeoutError(
            f"MCP tool '{tool_name}' did not respond within {timeout}s"
        ) from exc


class MCPToolClient:
    """Client for accessing MCP tools from one or more MCP servers.

    Supports both legacy single-server mode and multi-server mode via
    ToolRegistry.
    """

    def __init__(
        self,
        server_url: str | None = None,
        server_configs: dict[str, dict[str, Any]] | None = None,
        tool_registry: Optional["ToolRegistry"] = None,
    ):
        """Initialize the MCP client.

        Args:
            server_url: URL of a single MCP server (legacy mode). If None,
                       reads from MCP_SERVER_URL env var, falling back to
                       http://localhost:8888/mcp
            server_configs: Dict of server configs for multi-server mode.
                           Format: {server_id: {"transport": "...",
                           "url": "..."}}
            tool_registry: ToolRegistry instance for config-driven
                          multi-server mode. Takes precedence over
                          server_configs and server_url.

        At least one of server_url, server_configs, or tool_registry must be
        provided
        (or server_url will default from environment).
        """
        self._campaign_admission: CampaignAdmission | None = None
        self._tool_registry = tool_registry
        self._client: MultiServerMCPClient | None = None
        self._tools_dict: dict[str, Any] | None = None
        self._openai_tools: list[dict[str, Any]] | None = None
        self._initialize_lock = asyncio.Lock()
        self._tool_to_server: dict[str, str] = {}  # maps tool_name -> server_id

        self._server_configs = _resolve_server_configs(
            tool_registry, server_configs, server_url
        )

        # Store for backwards compatibility
        self.server_url = (
            next(iter(self._server_configs.values())).get("url")
            if self._server_configs
            else None
        )

    async def initialize(self) -> None:
        """Initialize the client and fetch available tools from all servers."""
        # Tool indexes, rather than transport construction, define readiness.
        # A concurrent caller must not observe the transport during the await
        # below and mistake that half-initialized state for a usable client.
        if self._tools_dict is not None:
            require_bound_mode(self._campaign_admission)
            logger.debug("MCP client already initialized")
            return

        async with self._initialize_lock:
            if self._tools_dict is not None:
                require_bound_mode(self._campaign_admission)
                logger.debug("MCP client initialized by concurrent caller")
                return
            await self._initialize_locked()

    async def _initialize_locked(self) -> None:
        """Discover and publish tools while the initialization lock is held."""
        if not self._server_configs:
            raise RuntimeError("no server configurations available")

        server_names = list(self._server_configs.keys())
        logger.info(
            "initializing MCP client for %s server(s): %s",
            len(server_names),
            server_names,
        )

        admission = await prepare_admission(self._server_configs)
        configs = (
            admission.transport_configs()
            if admission is not None
            else self._server_configs
        )
        client = MultiServerMCPClient(cast(dict[str, Connection], configs))
        # This round-trips to every configured server. Publish the client
        # only after its tool indexes are ready so all callers see one
        # complete initialization state.
        tools = await client.get_tools()
        if admission is not None:
            tools = [tool for tool in tools if tool.name in PUBLIC_TOOLS]
        self._campaign_admission = admission
        self._client = client
        self._index_tools(tools)

        assert self._tools_dict is not None  # set by _index_tools above
        logger.info(
            "MCP client initialized with %s tools: %s",
            len(self._tools_dict),
            list(self._tools_dict.keys()),
        )

    def _index_tools(self, tools: list[Any]) -> None:
        """Populate lookup structures from the tools fetched by initialize().

        Sets self._tools_dict (name -> tool), self._tool_to_server (name ->
        server id, where known via the tool registry), and self._openai_tools
        (the OpenAI-format conversion of `tools`, for LiteLLM).

        Args:
            tools: Tools fetched from self._client.get_tools().
        """
        # Create dict for easy lookup and track which server provides each tool
        self._tools_dict = {}
        self._tool_to_server = {}

        for tool in tools:
            self._tools_dict[tool.name] = tool
            # Infer server from tool metadata if available
            # MultiServerMCPClient prefixes tools with server name in some
            # versions For now, we'll track based on the tool registry if
            # available
            if self._tool_registry:
                tool_config = self._tool_registry.get_tool_by_mcp_name(
                    tool.name
                )
                if tool_config:
                    self._tool_to_server[tool.name] = tool_config.server

        # Convert to OpenAI format for LiteLLM
        self._openai_tools = [convert_to_openai_tool(tool) for tool in tools]

    async def _admit_campaign_tool(self, name: str) -> None:
        require_bound_mode(self._campaign_admission)
        if self._campaign_admission is not None:
            await self._campaign_admission.require_tool(
                name, self._server_configs
            )

    @staticmethod
    def _require_tool(tools_dict: dict[str, Any], tool_name: str) -> Any:
        """Return the tool object for tool_name, or raise if not found."""
        if tool_name not in tools_dict:
            raise ValueError(
                f"tool '{tool_name}' not found. "
                f"available tools: {list(tools_dict.keys())}"
            )
        return tools_dict[tool_name]

    # Direct-call convenience path used when the caller already knows the
    # tool name/args (e.g. availability checks, literature_review.py) --
    # contrast with execute_tool_call, which unpacks an LLM tool-call object.
    async def call_tool(self, tool_name: str, **kwargs: Any) -> str:
        """Call an MCP tool directly with arguments.

        This is a convenience method for calling tools directly without
        constructing a LiteLLM-style tool call object.

        Args:
            tool_name: Name of the tool to call
            **kwargs: Tool arguments as keyword arguments

        Returns:
            Tool result as a string (often JSON)

        Raises:
            RuntimeError: If client not initialized
            ValueError: If tool not found
        """
        await self._admit_campaign_tool(tool_name)
        tools_dict = _ensure_tools_initialized(self._tools_dict)
        tool = self._require_tool(tools_dict, tool_name)

        logger.debug("calling mcp tool: %s with args: %s", tool_name, kwargs)

        # Raises MCPToolTimeoutError on a dead call rather than returning a
        # sentinel: every caller on this path (the availability probe, each
        # literature source) already catches broadly and degrades, so a stuck
        # tool costs that one source instead of the whole run.
        result = _unwrap_tool_result(
            await _ainvoke_within_timeout(tool, kwargs, tool_name)
        )

        logger.debug(
            "mcp tool result for %s: %s",
            tool_name,
            truncate(str(result)),
        )

        return cast(str, result)

    @staticmethod
    async def _invoke_or_timeout_result(
        tool: Any, tool_args: dict[str, Any], tool_name: str
    ) -> str:
        """Invoke tool_name, reporting a timeout as its result string.

        Unlike call_tool, this runs under _execute_tool_calls' asyncio.gather
        without return_exceptions, so raising would take down every sibling
        tool call in the same turn and fail the run; telling the model this
        one tool did not answer lets it proceed on what it does have.
        """
        try:
            return cast(
                str,
                _unwrap_tool_result(
                    await _ainvoke_within_timeout(tool, tool_args, tool_name)
                ),
            )
        except MCPToolTimeoutError as exc:
            logger.warning("%s; reporting the timeout to the model", exc)
            return f"Error: {exc}. No result was returned."

    def _require_initialized_tools(self) -> dict[str, Any]:
        """Return self._tools_dict, raising if not yet initialized."""
        return _ensure_tools_initialized(self._tools_dict)

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Execute an MCP tool call.

        The returned dict's shape (role/name/tool_call_id/content) matches
        what call_llm_with_tools (llm/tools/loop.py) appends to its message
        history after invoking the tool_executor callback passed in by the
        caller (see tools/provider.py's ToolProvider.execute_tool_call, which
        wraps this method for tool-call-counting). Content is unwrapped from the
        MCP content-block list shape exactly like call_tool.

        Args:
            tool_call: Tool call object from LiteLLM with function name
                and arguments

        Returns:
            Dictionary formatted as a tool response message
        """
        tools_dict = self._require_initialized_tools()
        tool_name = tool_call.function.name
        await self._admit_campaign_tool(tool_name)
        tool_args = json.loads(tool_call.function.arguments)

        logger.debug(
            "executing mcp tool: %s with args: %s", tool_name, tool_args
        )
        result = await self._invoke_or_timeout_result(
            tools_dict[tool_name], tool_args, tool_name
        )
        logger.debug(
            "mcp tool result for %s: %s%s",
            tool_name,
            str(result)[:200],
            "..." if len(str(result)) > 200 else "",
        )

        return {
            "role": "tool",
            "name": tool_name,
            "tool_call_id": tool_call.id,
            "content": result,  # MCP tools return strings (often JSON)
        }

    # Callers (see tools/provider.py's MCPToolProvider.get_tools) pass a
    # workflow's whitelist here so a node's LLM only ever sees the subset of
    # tools that workflow's YAML config authorizes for that phase.
    def get_tools(
        self, whitelist: list[str] | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Get MCP tools, optionally filtered by whitelist.

        Args:
            whitelist: Optional list of tool names to include. If None,
                returns all tools.

        Returns:
            Tuple of (tools_dict, openai_tools) where:
            - tools_dict: Dict mapping tool names to tool objects
            - openai_tools: List of tools in OpenAI format for LiteLLM
        """
        require_bound_mode(self._campaign_admission)
        tools_dict = _ensure_tools_initialized(self._tools_dict)
        # A separate condition, not a restatement of the one above: both are
        # populated together by _index_tools, so an unset OpenAI-format list
        # is its own half-initialized state, and letting it through would
        # hand callers a None where they expect the LiteLLM tool schemas.
        if self._openai_tools is None:
            raise RuntimeError(NOT_INITIALIZED_MESSAGE)

        if whitelist is None:
            return tools_dict, self._openai_tools

        return _filter_tools_by_whitelist(tools_dict, whitelist)

    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool is available."""
        require_bound_mode(self._campaign_admission)
        if self._tools_dict is None:
            return False
        return tool_name in self._tools_dict


if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


# MCP clients own asyncio locks and SDK sessions. Durable worker cohorts use
# separate event loops, so each loop gets an independent config/policy cache.
# Weak keys release worker clients (and their captured headers) with the loop.
_global_clients: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[tuple[Any, bool], MCPToolClient]
] = weakref.WeakKeyDictionary()
_global_clients_lock = threading.Lock()


def _freeze_config(value: Any) -> Any:
    """Return a hashable representation of resolved MCP configuration."""
    if isinstance(value, dict):
        return tuple(
            sorted((key, _freeze_config(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_config(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_config(item) for item in value))
    try:
        hash(value)
    except TypeError:
        return (type(value), id(value))
    return value


async def _probe_literature_source(
    server_url: str | None,
    tool_registry: Optional["ToolRegistry"],
    check_tool_name: str | None,
    skip_availability_check: bool,
) -> bool:
    """Probes literature source availability via a throwaway MCP client.

    Args:
        server_url: URL of the MCP server (legacy).
        tool_registry: Optional ToolRegistry for config-driven tool lookup.
        check_tool_name: Availability-check tool name, or None to skip.
        skip_availability_check: Whether the server responding is enough,
            without a tool-specific check.

    Returns:
        True if the literature source is available, else False.
    """
    try:
        # One throwaway client serves both probes below. Deliberately not
        # the cached global client: a down server must not poison state.
        mcp_client = MCPToolClient(
            server_url=server_url, tool_registry=tool_registry
        )
        await mcp_client.initialize()
        return await _probe_literature_source_availability(
            mcp_client, check_tool_name, skip_availability_check
        )
    except Exception as e:
        # Deliberately broad: any MCP hiccup (connection refused, timeout,
        # malformed tool schema) degrades to "unavailable" here rather than
        # raising, so callers (e.g. HypothesisGenerator.prepare_task_state)
        # can fall back to LLM-only mode instead of aborting the run.
        logger.warning(
            "error checking literature source availability: %s: %s",
            type(e).__name__,
            e,
        )
        logger.debug("full traceback: %s", e, exc_info=True)
        return False


async def check_literature_source_available(
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
) -> bool:
    """Check if the literature source is available via MCP server.

    Queries the configured availability check tool (e.g.,
    check_pubmed_available)
    to verify the literature source is accessible.

    If no availability check tool is configured (availability_check: null in
    YAML),
    assumes the source is available as long as MCP server responds.

    Args:
        server_url: URL of the MCP server (legacy). If None, reads from
            MCP_SERVER_URL
        tool_registry: Optional ToolRegistry for config-driven tool lookup

    Returns:
        True if literature source is available via MCP server, False otherwise
    """
    check_tool_name, skip_availability_check = _resolve_availability_check_tool(
        tool_registry
    )

    if server_url is None and tool_registry is None:
        server_url = _resolve_server_url()

    return await _probe_literature_source(
        server_url, tool_registry, check_tool_name, skip_availability_check
    )


async def check_tool_available(
    tool_name: str,
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
) -> bool:
    """Check whether the MCP server advertises a specific tool.

    Some tools are registered conditionally by the server (``search_web``
    only appears when a provider API key is configured), so asking the
    server what it exposes is the only honest way to tell whether a
    capability is usable.

    Args:
        tool_name: MCP tool name to look for, e.g. "search_web".
        server_url: URL of the MCP server (legacy).
        tool_registry: Optional ToolRegistry for multi-server configs.

    Returns:
        True if the server responded and lists that tool, False otherwise.
    """
    if server_url is None and tool_registry is None:
        server_url = _resolve_server_url()

    try:
        test_client = MCPToolClient(
            server_url=server_url, tool_registry=tool_registry
        )
        await test_client.initialize()
        return test_client.has_tool(tool_name)
    except Exception as e:
        # Broad catch to False, matching the other probes here: this result
        # only gates whether a capability is offered, and an unreachable
        # server must degrade to "not available" rather than raise.
        logger.debug("tool availability check failed for %s: %s", tool_name, e)
        return False


# The MCP server's own verdict on whether a web search would reach a
# provider, and the tool it gates. Older server images expose only the
# second: the api and mcp services deploy separately, so the probe has to
# work against an image that predates the check.
WEB_SEARCH_CHECK_TOOL = "check_web_search_available"
WEB_SEARCH_TOOL = "search_web"


async def check_web_search_available(
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
) -> bool:
    """Check whether a web search issued now would reach a provider.

    Presence of ``search_web`` is not the same question. The server
    registers that tool when a provider key is *set*, which stays true
    after the provider starts refusing the key -- and since a refused
    search degrades to an empty result set, the connector then reads as
    healthy while every run gets nothing back. Ask the server instead,
    falling back to presence only against an image too old to answer.

    Args:
        server_url: URL of the MCP server (legacy).
        tool_registry: Optional ToolRegistry for multi-server configs.

    Returns:
        True if a web search would reach a provider, False otherwise --
        including when the server is unreachable.
    """
    if server_url is None and tool_registry is None:
        server_url = _resolve_server_url()

    try:
        probe_client = MCPToolClient(
            server_url=server_url, tool_registry=tool_registry
        )
        await probe_client.initialize()
        tools, _ = probe_client.get_tools()
        if WEB_SEARCH_CHECK_TOOL in tools:
            return await _call_check_tool(
                probe_client, WEB_SEARCH_CHECK_TOOL, tools
            )
        return WEB_SEARCH_TOOL in tools
    except Exception as e:
        # Broad catch to False, matching the probes around it: an
        # unreachable server means the capability is not usable now.
        logger.debug("web search availability check failed: %s", e)
        return False


async def check_mcp_available(
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
) -> bool:
    """Check if MCP server is available and responding.

    Args:
        server_url: URL of the MCP server (legacy)
        tool_registry: Optional ToolRegistry for multi-server configs

    Returns:
        True if MCP server is available and responding, False otherwise
    """
    if server_url is None and tool_registry is None:
        server_url = _resolve_server_url()

    try:
        _log_mcp_test_start(tool_registry, server_url)

        test_client = MCPToolClient(
            server_url=server_url, tool_registry=tool_registry
        )
        await test_client.initialize()

        # Check if we got any tools
        tools_dict = test_client._tools_dict
        return _has_any_tools(tools_dict)

    except Exception as e:
        # Same broad-catch-to-False fallback as
        # check_literature_source_available: an unreachable server here must
        # not raise, since this result gates whether the literature_review
        # node is added to the graph at all (see generator.py).
        _log_mcp_unavailable(tool_registry, server_url, e)
        return False


async def get_mcp_client(
    server_url: str | None = None,
    tool_registry: Optional["ToolRegistry"] = None,
    force_new: bool = False,
) -> MCPToolClient:
    """Get or create the global MCP client instance.

    Args:
        server_url: URL of the MCP server (legacy)
        tool_registry: Optional ToolRegistry for config-driven setup
        force_new: If True, create a new client even if one exists

    Returns:
        Initialized MCPToolClient instance
    """
    configs = _resolve_server_configs(tool_registry, None, server_url)
    key = (_freeze_config(configs), campaign_free_mode())
    loop = asyncio.get_running_loop()
    with _global_clients_lock:
        for cached_loop in list(_global_clients):
            if cached_loop.is_closed():
                del _global_clients[cached_loop]
        loop_clients = _global_clients.setdefault(loop, {})
        if force_new or key not in loop_clients:
            loop_clients[key] = MCPToolClient(
                server_url=server_url, tool_registry=tool_registry
            )

    # Always ensure it's initialized (safe to call multiple times)
    client = loop_clients[key]
    await client.initialize()

    return client


def reset_mcp_client() -> None:
    """Reset the global MCP client (primarily for testing)."""
    with _global_clients_lock:
        _global_clients.clear()
