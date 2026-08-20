"""JSON schemas for the deep-research loop's five model calls.

These pair with the ``research_*`` prompt templates and are reached
through ``get_schema_for_prompt`` like every other stage. The loop itself
(``co_scientist.research``) never sees them -- it states its needs as a
protocol, and ``co_scientist.research_adapter.model`` is what answers
with these.

Note what ``RESEARCH_EXTRACT_SCHEMA`` does not do: it identifies a
document by the index the prompt printed beside it, never by echoing its
title or locator back. An echoing schema makes output length scale with
the number of documents read, which is how a wide level truncates its
JSON identically on every retry and degrades silently. The quoted span
stays, because a finding that cannot be quoted has not been found.
"""

from typing import Any

from co_scientist.schemas.builders import obj, str_array

RESEARCH_STANCES_SCHEMA: dict[str, Any] = {
    "name": "research_stances",
    "strict": False,
    "schema": obj(
        {
            "stances": str_array(
                "Distinct perspectives to research the goal from, each a"
                " short noun phrase (e.g. mechanism, contradicting"
                " evidence, methodology, prior art)"
            )
        }
    ),
}

RESEARCH_QUESTIONS_SCHEMA: dict[str, Any] = {
    "name": "research_questions",
    "strict": False,
    "schema": obj(
        {
            "questions": str_array(
                "Answerable questions this stance needs settled, each"
                " narrow enough for one literature search"
            )
        }
    ),
}

RESEARCH_QUERY_SCHEMA: dict[str, Any] = {
    "name": "research_query",
    "strict": False,
    "schema": obj(
        {
            "query": {
                "type": "string",
                "description": (
                    "The question rendered as a literature search query:"
                    " the terms a source indexes on, not a sentence"
                ),
            }
        }
    ),
}

RESEARCH_EXTRACT_SCHEMA: dict[str, Any] = {
    "name": "research_extract",
    "strict": False,
    "schema": obj(
        {
            "findings": {
                "type": "array",
                "description": (
                    "What the documents actually say about the question."
                    " Omit anything you cannot quote."
                ),
                "items": obj(
                    {
                        "document": {
                            "type": "integer",
                            "description": (
                                "Index of the document this comes from,"
                                " as numbered in the prompt"
                            ),
                        },
                        "claim": {
                            "type": "string",
                            "description": (
                                "The finding in your own words, one sentence"
                            ),
                        },
                        "quote": {
                            "type": "string",
                            "description": (
                                "The passage from that document which"
                                " supports the claim, verbatim"
                            ),
                        },
                    }
                ),
            },
            "follow_ups": str_array(
                "Questions this reading raised and did not answer. Leave"
                " empty when the documents settled the question."
            ),
        }
    ),
}

RESEARCH_COMPRESS_SCHEMA: dict[str, Any] = {
    "name": "research_compress",
    "strict": False,
    "schema": obj(
        {
            "summary": {
                "type": "string",
                "description": (
                    "What this question's reading established, in a few"
                    " sentences, including where the sources disagree"
                ),
            }
        }
    ),
}
