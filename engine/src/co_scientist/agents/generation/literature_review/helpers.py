"""Literature review helper functions (compatibility facade).

The helper implementations live in four focused modules, split by the node
phase they support:

- ``search_support``: search config, response normalization, query
  generation, and result merging (Phases 1-2).
- ``search_budget``: evidence-budget selection over the merged, ranked
  results (Phase 2 reduction).
- ``retrieval_support``: PDF discovery and content fetching (Phases 2.4-2.5).
- ``article_support``: article assembly, fulltext availability, and node
  result construction.

Every helper (including the private ones exercised by tests) is re-exported
here so ``literature_review.helpers`` stays the stable import path used by the
sibling phase modules and the test suite.
"""

from co_scientist.agents.generation.literature_review.article_support import (
    _YEAR_PARSERS as _YEAR_PARSERS,
)
from co_scientist.agents.generation.literature_review.article_support import (
    _build_article_url as _build_article_url,
)
from co_scientist.agents.generation.literature_review.article_support import (
    _has_analyzable_content as _has_analyzable_content,
)
from co_scientist.agents.generation.literature_review.article_support import (
    _has_fulltext as _has_fulltext,
)
from co_scientist.agents.generation.literature_review.article_support import (
    _year_from_date_revised as _year_from_date_revised,
)
from co_scientist.agents.generation.literature_review.article_support import (
    _year_from_year_field as _year_from_year_field,
)
from co_scientist.agents.generation.literature_review.article_support import (
    build_article_from_metadata as build_article_from_metadata,
)
from co_scientist.agents.generation.literature_review.article_support import (
    build_articles_from_metadata as build_articles_from_metadata,
)
from co_scientist.agents.generation.literature_review.article_support import (
    count_papers_with_fulltext as count_papers_with_fulltext,
)
from co_scientist.agents.generation.literature_review.article_support import (
    get_paper_content_for_analysis as get_paper_content_for_analysis,
)
from co_scientist.agents.generation.literature_review.article_support import (
    get_papers_with_content as get_papers_with_content,
)
from co_scientist.agents.generation.literature_review.article_support import (
    make_failure_result as make_failure_result,
)
from co_scientist.agents.generation.literature_review.article_support import (
    make_success_result as make_success_result,
)
from co_scientist.agents.generation.literature_review.article_support import (
    parse_year_from_metadata as parse_year_from_metadata,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    ContentToolConfig as ContentToolConfig,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _content_or_text_field as _content_or_text_field,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _first_link_url as _first_link_url,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _lookup_source_config as _lookup_source_config,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _parse_content_from_dict as _parse_content_from_dict,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _parse_content_from_string as _parse_content_from_string,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _parse_pdf_url_from_string as _parse_pdf_url_from_string,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _pdf_url_from_dict as _pdf_url_from_dict,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _pdf_url_from_list as _pdf_url_from_list,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _pdf_url_from_parsed as _pdf_url_from_parsed,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _resolve_content_entry as _resolve_content_entry,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _resolve_content_tool as _resolve_content_tool,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _resolve_pdf_discovery_entry as _resolve_pdf_discovery_entry,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    _resolve_pdf_discovery_tool as _resolve_pdf_discovery_tool,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    build_content_config as build_content_config,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    build_pdf_discovery_config as build_pdf_discovery_config,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    get_papers_needing_content as get_papers_needing_content,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    get_papers_needing_pdf_discovery as get_papers_needing_pdf_discovery,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    parse_content_result as parse_content_result,
)
from co_scientist.agents.generation.literature_review.retrieval_support import (
    parse_pdf_discovery_result as parse_pdf_discovery_result,
)
from co_scientist.agents.generation.literature_review.search_budget import (
    _exclude_retracted as _exclude_retracted,
)
from co_scientist.agents.generation.literature_review.search_budget import (
    _fill_remaining_by_score as _fill_remaining_by_score,
)
from co_scientist.agents.generation.literature_review.search_budget import (
    _fill_reserved_slots as _fill_reserved_slots,
)
from co_scientist.agents.generation.literature_review.search_budget import (
    select_within_budget as select_within_budget,
)
from co_scientist.agents.generation.literature_review.search_support import (
    SearchConfig as SearchConfig,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _collect_enabled_source_types as _collect_enabled_source_types,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _determine_multi_source_query_type as _determine_multi_source_query_type,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _extract_results_path as _extract_results_path,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _is_duplicate_title as _is_duplicate_title,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _multi_source_type_if_applicable as _multi_source_type_if_applicable,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _normalize_title as _normalize_title,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _normalize_with_response_format as _normalize_with_response_format,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _paper_id_for_rekey as _paper_id_for_rekey,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _quoted_field_mapping_source as _quoted_field_mapping_source,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _rekey_list_response_by_id as _rekey_list_response_by_id,
)
from co_scientist.agents.generation.literature_review.search_support import (
    _resolve_source_id_field as _resolve_source_id_field,
)
from co_scientist.agents.generation.literature_review.search_support import (
    determine_query_source_type as determine_query_source_type,
)
from co_scientist.agents.generation.literature_review.search_support import (
    extract_source_name as extract_source_name,
)
from co_scientist.agents.generation.literature_review.search_support import (
    merge_search_results as merge_search_results,
)
from co_scientist.agents.generation.literature_review.search_support import (
    normalize_search_response as normalize_search_response,
)
from co_scientist.agents.generation.literature_review.search_support import (
    parse_mcp_query_result as parse_mcp_query_result,
)
