"""Shared evidence gathering for Generation, Reflection and research adapters.

Search configuration, source fan-out, ranking, retries, budget reduction and
article construction belong here. Agent-specific query planning, analysis,
synthesis and failure presentation stay with their agents.
"""

from co_scientist.evidence.article_support import (
    build_articles_from_metadata as build_articles_from_metadata,
)
from co_scientist.evidence.run_config import (
    search_config_for as search_config_for,
)
from co_scientist.evidence.search import collect_papers as collect_papers
from co_scientist.evidence.search_support import SearchConfig as SearchConfig
