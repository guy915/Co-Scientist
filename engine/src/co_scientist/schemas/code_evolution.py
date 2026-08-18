"""Response schema for proposing one code variant.

Note what the schema does *not* contain: the parent program. A variant
proposal sees a whole program and returns an edit to it, so a schema
that asked the model to echo the result back would make output length
scale with program size -- the same shape that silently truncated
proximity clustering on large pools, and with the same signature (an
identical failure on every retry, and a variant that appears to have
been skipped). The patch envelope is proportional to the change instead.
"""

from typing import Any

from co_scientist.schemas.builders import obj

CODE_EVOLUTION_SCHEMA: dict[str, Any] = {
    "name": "code_variant_proposal",
    "strict": False,
    "schema": obj(
        {
            "rationale": {
                "type": "string",
                "description": (
                    "Why this specific edit should move the objective,"
                    " naming the measurement or the captured error that"
                    " points at it. Two to four sentences."
                ),
            },
            "patch": {
                "type": "string",
                "description": (
                    "The complete V4A patch envelope, beginning with"
                    " '*** Begin Patch' and ending with '*** End Patch'."
                    " Context lines must be copied exactly from the"
                    " parent program; they are what proves the edit was"
                    " written against the current code."
                ),
            },
            "expected_effect": {
                "type": "string",
                "description": (
                    "What the objective metric should do if the"
                    " reasoning holds, in one sentence. Stated before"
                    " the run so a wrong prediction is legible as one."
                ),
            },
        }
    ),
}
