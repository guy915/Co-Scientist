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
"""Response parser for converting MCP tool responses to Article objects.

Supports dynamic field mapping with transformations defined in YAML configs.
"""

import json
import logging
import re
from typing import Any

from co_scientist.config.schema import ToolConfig
from co_scientist.models import Article

logger = logging.getLogger(__name__)


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
            if self.response_format.type == "boolean_string":
                return response.lower() == "true"
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                logger.warning("failed to parse JSON response: %s...",
                               response[:100])
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

        articles = []

        if self.response_format.is_dict:
            # Results is a dict {key: item}
            if not isinstance(results, dict):
                logger.warning("expected dict but got %s", type(results))
                return []

            for key, item in results.items():
                try:
                    article = self._map_item_to_article(item, dict_key=key)
                    if article:
                        articles.append(article)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error("failed to map item %s: %s", key, e)
        else:
            # Results is a list
            if not isinstance(results, list):
                # Try to treat as single item
                results = [results]

            for i, item in enumerate(results):
                try:
                    article = self._map_item_to_article(item)
                    if article:
                        articles.append(article)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error("failed to map item %s: %s", i, e)

        logger.debug("parsed %s articles from response", len(articles))
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

        parts = path.split(".")
        current = data

        for part in parts:
            if current is None:
                return None

            # Handle array index notation
            match = re.match(r"(\w+)\[(\d+)\]", part)
            if match:
                field, index = match.groups()
                if field:
                    current = current.get(field) if isinstance(current,
                                                               dict) else None
                if current is not None and isinstance(current, list):
                    idx = int(index)
                    current = current[idx] if idx < len(current) else None
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None

        return current

    def _map_item_to_article(self,
                             item: dict[str, Any],
                             dict_key: str | None = None) -> Article | None:
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

        mapping = self.response_format.field_mapping

        # Build kwargs for Article
        kwargs: dict[str, Any] = {}

        # Map each field
        for article_field, expr in mapping.items():
            try:
                value = self._evaluate_expression(expr, item, dict_key)
                kwargs[article_field] = value
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug("failed to evaluate %s=%s: %s", article_field,
                             expr, e)
                # Use None for failed mappings
                kwargs[article_field] = None

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
            source=kwargs.get("source", self.tool_config.source_type),
            pdf_links=kwargs.get("pdf_links", []),
            used_in_analysis=True,
        )

    def _evaluate_expression(self,
                             expr: str,
                             item: dict[str, Any],
                             dict_key: str | None = None) -> Any:
        """Evaluate a field mapping expression.

        Supported expressions:
        - "fieldname" -> item["fieldname"]
        - "@key" -> dict_key
        - "@url_from_key" -> construct PubMed URL from dict_key
        - "'static'" -> "static" (quoted string)
        - "field|transform1|transform2" -> apply transforms

        Transforms:
        - split:DELIM -> split string by delimiter
        - index:N -> get Nth element
        - int -> convert to integer
        - default:VALUE -> use VALUE if None

        Args:
            expr: Expression string
            item: Data item dict
            dict_key: Optional dict key for "@key" expressions

        Returns:
            Evaluated value
        """
        # Handle static values (quoted strings)
        if expr.startswith("'") and expr.endswith("'"):
            return expr[1:-1]

        # Handle special @key expressions
        if expr == "@key":
            return dict_key

        if expr == "@url_from_key":
            # Construct PubMed URL from paper ID
            if dict_key:
                return f"https://pubmed.ncbi.nlm.nih.gov/{dict_key}/"
            return None

        # Check for transform chain
        if "|" in expr:
            parts = expr.split("|")
            field_expr = parts[0]
            transforms = parts[1:]

            # Get initial value
            value = self._get_field_value(field_expr, item, dict_key)

            # Apply transforms
            for transform in transforms:
                value = self._apply_transform(transform, value)

            return value

        # Simple field access
        return self._get_field_value(expr, item, dict_key)

    def _get_field_value(self,
                         field_expr: str,
                         item: dict[str, Any],
                         dict_key: str | None = None) -> Any:
        """Get a field value from item, supporting nested paths."""
        if field_expr == "@key":
            return dict_key

        # Handle nested paths
        if "." in field_expr:
            return self._navigate_path(item, field_expr)

        return item.get(field_expr)

    def _apply_transform(self, transform: str, value: Any) -> Any:
        """Apply a transform to a value.

        Args:
            transform: Transform specification
                (e.g., "split:/", "index:0", "int")
            value: Value to transform

        Returns:
            Transformed value
        """
        if value is None:
            # Check for default transform
            if transform.startswith("default:"):
                default_value = transform[8:]
                # Try to parse as int
                try:
                    return int(default_value)
                except ValueError:
                    return default_value
            return None

        # Split transform
        if transform.startswith("split:"):
            delimiter = transform[6:]
            if isinstance(value, str):
                return value.split(delimiter)
            return value

        # Index transform
        if transform.startswith("index:"):
            index = int(transform[6:])
            if isinstance(value, (list, tuple)) and len(value) > index:
                return value[index]
            return None

        # Int transform
        if transform == "int":
            try:
                return int(value)
            except (ValueError, TypeError):
                return None

        # Float transform
        if transform == "float":
            try:
                return float(value)
            except (ValueError, TypeError):
                return None

        # Default transform
        if transform.startswith("default:"):
            if value is None:
                default_value = transform[8:]
                try:
                    return int(default_value)
                except ValueError:
                    return default_value
            return value

        # wrap_list transform - wrap single value in a list
        if transform == "wrap_list":
            if value is None:
                return []
            if isinstance(value, list):
                return value
            return [value]

        logger.warning("unknown transform: %s", transform)
        return value


def parse_tool_response(response: Any,
                        tool_config: ToolConfig) -> list[Article] | bool | Any:
    """Convenience function to parse a tool response.

    Args:
        response: Raw response from MCP tool
        tool_config: Tool configuration

    Returns:
        Parsed response (List[Article] for search tools, bool for utility, etc.)
    """
    parser = ResponseParser(tool_config)

    # For boolean responses
    if tool_config.response_format.type == "boolean_string":
        return parser.parse_response(response)

    # For search tools, parse to articles
    if tool_config.category in ("search", "search_with_content"):
        return parser.parse_to_articles(response)

    # For other tools, just parse the response
    return parser.parse_response(response)
