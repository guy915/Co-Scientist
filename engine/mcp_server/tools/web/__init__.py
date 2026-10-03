"""Web search and page-fetching tools.

Gives the co-scientist access to the open web alongside its academic
sources: ``search_web`` finds pages, ``read_url`` reads them.
"""

from mcp_server.tools.web.fetch import read_url
from mcp_server.tools.web.providers import (
    check_web_search_available,
    search_web,
)

__all__ = ["check_web_search_available", "read_url", "search_web"]
