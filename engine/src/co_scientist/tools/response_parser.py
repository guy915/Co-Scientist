"""Response parser for converting MCP tool responses to Article objects.

Supports dynamic field mapping with transformations defined in YAML configs.
"""

import json
import logging
import re
from typing import Any

from co_scientist.config.schema import ToolConfig
from co_scientist.models import Article
from co_scientist.tools.response_parser_transforms import apply_transform

logger = logging.getLogger(__name__)

# Matches a "field[N]" (or "[N]") array-index path segment; compiled once
# here rather than on every path segment descended during response parsing.
_INDEXED_PART_RE = re.compile(r"(\w+)\[(\d+)\]")


def _is_quoted_literal(expr: str) -> bool:
    """True when expr is a single-quoted static string literal ('...')."""
    return expr.startswith("'") and expr.endswith("'")


def _url_from_key(dict_key: str | None) -> str | None:
    """Construct the PubMed article URL for a dict-results mapping's key.

    Args:
        dict_key: The raw PubMed ID key, or None if results were not
            dict-shaped.

    Returns:
        The article URL, or None if dict_key is missing or empty.
    """
    if dict_key:
        return f"https://pubmed.ncbi.nlm.nih.gov/{dict_key}/"
    return None


def _get_dict_field(current: Any, field: str) -> Any:
    """Return current[field] when current is a dict, else None."""
    return current.get(field) if isinstance(current, dict) else None


def _index_into_list(current: Any, index: str) -> Any:
    r"""Index into current at position index, if current is a non-None list.

    Args:
        current: Value to index into.
        index: String-encoded non-negative index (matched by the caller's
            "(\w+)\[(\d+)\]" regex).

    Returns:
        current unchanged when it is None or not a list (the index is then
        ignored); otherwise the element at int(index), or None if the
        index is out of range.
    """
    if current is None or not isinstance(current, list):
        return current
    idx = int(index)
    return current[idx] if idx < len(current) else None


# Instantiated per tool call (see nodes/generation/literature_tools/
# validate.py) with that tool's ToolConfig, so a single MCP response-shape
# difference between e.g. PubMed and arXiv is absorbed entirely by YAML
# field_mapping expressions rather than per-source parsing code.
class ResponseParser:
    """Parse MCP tool responses using YAML-defined field mappings.

    Supports:
    - Direct field access: "title" -> item["title"]
    - Dict key as value: "@key" -> dict key
    - URL from key: "@url_from_key" -> constructs URL from dict key
    - Static values: "'pubmed'" -> "pubmed"
    - Transform chains: "date_revised|split:/|index:0|int"
    - Nested paths: "metadata.title" -> item["metadata"]["title"]
    - Default values: "citations|default:0"
    - Wrap in list: "pdf_url|wrap_list" -> [value] if not None
    """

    def __init__(self, tool_config: ToolConfig):
        """Initialize parser with tool configuration.

        Args:
            tool_config: Tool configuration containing response_format
        """
        self.tool_config = tool_config
        self.response_format = tool_config.response_format

    def parse_response(self, response: Any) -> Any:
        """Parse raw response based on response_format type.

        Args:
            response: Raw response from MCP tool (string or dict/list)

        Returns:
            Parsed response data
        """
        # Handle string responses (JSON)
        if isinstance(response, str):
            response = response.strip()
            # Some tools (e.g. availability checks) return the literal
            # string "true"/"false" instead of JSON; short-circuit before
            # attempting a JSON parse for that response type.
            if self.response_format.type == "boolean_string":
                return response.lower() == "true"
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                logger.warning(
                    "failed to parse JSON response: %s...", response[:100]
                )
                return response

        return response

    def parse_to_articles(self, response: Any) -> list[Article]:
        """Parse tool response into Article objects.

        Args:
            response: Raw response from MCP tool

        Returns:
            List of Article objects
        """
        # Parse raw response
        data = self.parse_response(response)

        if data is None:
            return []

        # Navigate to results using results_path
        results = self._navigate_path(data, self.response_format.results_path)

        if results is None:
            logger.warning("results_path returned None")
            return []

        articles = self._map_results(results, self.response_format.is_dict)

        logger.debug("parsed %s articles from response", len(articles))
        return articles

    def _map_results(self, results: Any, is_dict: bool) -> list[Article]:
        """Map raw results (a dict or a list) to Article objects.

        Each item is mapped independently, so one malformed item is logged
        and skipped rather than aborting the whole response.

        Args:
            results: The value found at results_path: a dict keyed by
                source id (e.g. PubMed PMIDs) when is_dict is True, or a
                list (or single item, coerced to a one-item list).
            is_dict: Whether results is expected to be a dict.

        Returns:
            List of successfully-mapped Article objects.
        """
        if is_dict:
            return self._map_dict_results(results)
        return self._map_list_results(results)

    def _map_dict_results(self, results: Any) -> list[Article]:
        """Map a dict-shaped results value ({key: item}) to Article objects.

        Some sources (e.g. PubMed, keyed by PMID) return a mapping rather
        than a list, and the key itself is needed for "@key"/
        "@url_from_key" expressions in field mappings, so it is threaded
        through as dict_key per item.

        Args:
            results: The value found at results_path, expected to be a dict.

        Returns:
            List of successfully-mapped Article objects.
        """
        articles = []

        if not isinstance(results, dict):
            logger.warning("expected dict but got %s", type(results))
            return []

        for key, item in results.items():
            try:
                article = self._map_item_to_article(item, dict_key=key)
                if article:
                    articles.append(article)
            except Exception as e:
                logger.error("failed to map item %s: %s", key, e)

        return articles

    def _map_list_results(self, results: Any) -> list[Article]:
        """Map a list-shaped results value to Article objects.

        Args:
            results: The value found at results_path: a list, or a single
                item that is coerced to a one-item list.

        Returns:
            List of successfully-mapped Article objects.
        """
        articles = []

        if not isinstance(results, list):
            # Try to treat as single item
            results = [results]

        for i, item in enumerate(results):
            try:
                article = self._map_item_to_article(item)
                if article:
                    articles.append(article)
            except Exception as e:
                logger.error("failed to map item %s: %s", i, e)

        return articles

    def _navigate_path(self, data: Any, path: str) -> Any:
        """Navigate to a nested path in data.

        Args:
            data: Data structure to navigate
            path: Dot-separated path (e.g., "results.items" or "." for root)

        Returns:
            Value at path, or None if not found
        """
        if path == "." or not path:
            return data

        current = data
        for part in path.split("."):
            if current is None:
                return None
            current = self._navigate_path_part(current, part)

        return current

    def _navigate_path_part(self, current: Any, part: str) -> Any:
        """Descend one dot-separated path segment from current.

        Args:
            current: Non-None value to descend from.
            part: A single path segment, e.g. "field" or "field[N]".

        Returns:
            The value at part, or None if it cannot be resolved.
        """
        # Handle array index notation
        # "field[N]" first descends into "field", then indexes into the
        # resulting list; a bare "[N]" (empty field) indexes directly.
        match = _INDEXED_PART_RE.match(part)
        if match:
            return self._navigate_indexed_part(current, match)
        if isinstance(current, dict):
            return current.get(part)
        # Non-dict, non-indexed segment with no further way to descend
        # (e.g. path continues past a scalar or a list).
        return None

    def _navigate_indexed_part(
        self, current: Any, match: "re.Match[str]"
    ) -> Any:
        r"""Resolve a "field[N]" (or "[N]") path segment against current.

        Args:
            current: Non-None value to descend from.
            match: Match of the "(\w+)\[(\d+)\]" pattern against the
                path segment.

        Returns:
            The indexed value, or the field-only descent result if it is
            not a list (index is then ignored), or None.
        """
        field, index = match.groups()
        if field:
            current = _get_dict_field(current, field)
        return _index_into_list(current, index)

    def _map_item_to_article(
        self, item: dict[str, Any], dict_key: str | None = None
    ) -> Article | None:
        """Map a single result item to an Article object.

        Args:
            item: Result item dict
            dict_key: Optional dict key (for is_dict=True results)

        Returns:
            Article object or None if mapping fails
        """
        if not isinstance(item, dict):
            logger.warning("expected dict item but got %s", type(item))
            return None

        kwargs = self._map_fields(item, dict_key)

        # Ensure required field (title)
        if not kwargs.get("title"):
            logger.warning("article missing title, skipping")
            return None

        # Create Article with mapped fields
        return Article(
            title=kwargs.get("title", ""),
            url=kwargs.get("url"),
            authors=kwargs.get("authors", []),
            year=kwargs.get("year"),
            venue=kwargs.get("venue"),
            citations=kwargs.get("citations", 0),
            abstract=kwargs.get("abstract"),
            content=kwargs.get("content"),
            source_id=kwargs.get("source_id"),
            # Fall back to the tool's configured source_type when the YAML
            # field_mapping does not set a "source" expression explicitly.
            source=kwargs.get("source", self.tool_config.source_type),
            pdf_links=kwargs.get("pdf_links", []),
            used_in_analysis=True,
        )

    def _map_fields(
        self, item: dict[str, Any], dict_key: str | None
    ) -> dict[str, Any]:
        """Evaluate every field_mapping expression against item.

        Each field is evaluated independently so a single malformed
        expression (bad transform, missing nested key) degrades to a None
        value for that field instead of dropping the article.

        Args:
            item: Result item dict.
            dict_key: Optional dict key (for is_dict=True results).

        Returns:
            Dict of Article field name to evaluated value (kwargs suitable
            for Article construction).
        """
        mapping = self.response_format.field_mapping
        kwargs: dict[str, Any] = {}

        for article_field, expr in mapping.items():
            try:
                kwargs[article_field] = self._evaluate_expression(
                    expr, item, dict_key
                )
            except Exception as e:
                logger.debug(
                    "failed to evaluate %s=%s: %s", article_field, expr, e
                )
                # Use None for failed mappings
                kwargs[article_field] = None

        return kwargs

    def _evaluate_expression(
        self, expr: str, item: dict[str, Any], dict_key: str | None = None
    ) -> Any:
        """Evaluate a field mapping expression.

        Expressions: "fieldname" (item lookup), "@key" (dict_key),
        "@url_from_key" (PubMed URL from dict_key), "'static'" (quoted
        literal), or "field|transform1|transform2" (pipe chain of
        transforms: split:DELIM, index:N, int, default:VALUE).

        Args:
            expr: Expression string
            item: Data item dict
            dict_key: Optional dict key for "@key" expressions

        Returns:
            Evaluated value
        """
        # Handle static values (quoted strings). Lets a YAML field_mapping
        # pin a constant field value (e.g. "'pubmed'") without there being a
        # matching key in the raw response item.
        if _is_quoted_literal(expr):
            return expr[1:-1]

        # Handle special @key expressions
        if expr == "@key":
            return dict_key

        if expr == "@url_from_key":
            return _url_from_key(dict_key)

        # Pipe-separated expressions apply a chain of transforms, e.g.
        # "date_revised|split:/|index:0|int" first splits on "/", then
        # takes the first element, then casts it.
        if "|" in expr:
            return self._evaluate_transform_chain(expr, item, dict_key)

        # Simple field access
        return self._get_field_value(expr, item, dict_key)

    def _evaluate_transform_chain(
        self, expr: str, item: dict[str, Any], dict_key: str | None
    ) -> Any:
        """Evaluate a "field|transform1|transform2|..." pipe expression.

        Args:
            expr: Pipe-separated expression; the first segment names the
                field, the rest are transforms applied left to right.
            item: Data item dict.
            dict_key: Optional dict key for a "@key" field segment.

        Returns:
            The field value with every transform applied in order.
        """
        parts = expr.split("|")
        field_expr = parts[0]
        transforms = parts[1:]

        value = self._get_field_value(field_expr, item, dict_key)
        for transform in transforms:
            value = self._apply_transform(transform, value)

        return value

    def _apply_transform(self, transform: str, value: Any) -> Any:
        """Apply a transform to a value.

        Thin method wrapper delegating to the shared transform vocabulary in
        response_parser_transforms; kept as a method so callers (and tests)
        can invoke it on a ResponseParser instance.

        Args:
            transform: Transform specification
                (e.g., "split:/", "index:0", "int")
            value: Value to transform

        Returns:
            Transformed value
        """
        return apply_transform(transform, value)

    def _get_field_value(
        self, field_expr: str, item: dict[str, Any], dict_key: str | None = None
    ) -> Any:
        """Get a field value from item, supporting nested paths."""
        if field_expr == "@key":
            return dict_key

        # Handle nested paths
        # e.g. "metadata.title", delegating to the same dotted-path
        # navigator used for results_path.
        if "." in field_expr:
            return self._navigate_path(item, field_expr)

        return item.get(field_expr)


def parse_mcp_result(result: Any) -> Any:
    """Decodes a raw MCP tool result that may arrive as a JSON string.

    MCP tools return either already-decoded Python data or a JSON-encoded
    string depending on transport. This is the canonical decode step; callers
    keep their own handling of malformed JSON.

    Args:
        result: Raw MCP tool result.

    Returns:
        The decoded object for JSON strings, otherwise the value unchanged.

    Raises:
        json.JSONDecodeError: If result is a string that is not valid JSON.
    """
    if isinstance(result, str):
        return json.loads(result)
    return result
