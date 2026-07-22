"""Shared fixture config for the tool-registry test files.

Used by ``test_config_registry`` and ``test_config_registry_tools``: a
custom-config YAML body plus the writer that lands it under ``tmp_path``
so registry behavior never depends on the developer's home directory.
"""

import textwrap
from pathlib import Path

# A self-contained config that fully replaces the bundled default
# (``settings.merge_strategy: replace``), so the resulting registry contains
# only the tools/servers/workflows defined here. Values are literal (no ${...}
# placeholders) so env-var substitution is a no-op and the tests are
# deterministic regardless of the environment.
REPLACE_CONFIG = textwrap.dedent("""
    version: "2.0"
    servers:
      myserver:
        url: "http://example.test/mcp"
        transport: "streamable_http"
        enabled: true
      offserver:
        url: "http://off.test/mcp"
        enabled: false
    tools:
      search_tools:
        alpha_search:
          server: "myserver"
          mcp_tool_name: "search_alpha"
          display_name: "Alpha Search"
          category: "search"
          enabled: true
        beta_search:
          server: "myserver"
          mcp_tool_name: "search_beta"
          enabled: false
      utility_tools:
        gamma_util:
          server: "myserver"
          mcp_tool_name: "util_gamma"
          enabled: true
    workflows:
      literature_review:
        primary_search: "alpha_search"
        fallback_search: "beta_search"
        availability_check: "gamma_util"
      draft_generation:
        search_tools:
          - "alpha_search"
          - "beta_search"
    enrichments:
      - tool: "gamma_util"
        output_key: "gamma_out"
        enabled: true
        workflow: "generation"
      - tool: "alpha_search"
        output_key: "alpha_out"
        enabled: true
        workflow: "reflection"
      - tool: "beta_search"
        output_key: "beta_out"
        enabled: false
        workflow: "generation"
    prompts:
      domain_context: "test domain context"
      generation_guidance: "test generation guidance"
    settings:
      merge_strategy: "replace"
    """)


def write_config(tmp_path: Path, body: str) -> str:
    """Write ``body`` to a YAML file under ``tmp_path`` and return its path."""
    path = tmp_path / "tools.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)
