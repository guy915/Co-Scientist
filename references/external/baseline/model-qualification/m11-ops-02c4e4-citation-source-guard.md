# M11-OPS-02c4e4 — cited-passage source guard

**Classification:** local design choice enforcing existing evidence provenance; the external model response is diagnostic evidence, not a claim about Google's private implementation.

**Gap and user effect:** the completed [Groq Qwen scientific screen](groq-qwen38-science-2026-09-27-1.json) returned `supports` for `matching_scope_full_support` while naming passage 2 and quoting text that exists only in passage 4, the separate contradiction control. The shared span resolver searched every shown passage after the named passage missed, reattributed the quote to passage 4, and retained `supports`. A lone edge with that pattern could be published as supported evidence.

**Local boundary:** `app.claims_span._resolve_span` serves both `assess_claim` and `assess_claims_batch`. The batch assessor receives a union of passages for all claims. The report gate consumes the resulting label and span; it cannot infer whether the model's named passage matched the quote. The preexisting `test_verbatim_quote_under_a_wrong_id_resolves_to_its_own_passage` explicitly pinned the permissive behavior.

**Acceptance:** when a cited key resolves to a shown passage, its quote must be locatable in that passage. An unmatched quote is discarded, downgrading an otherwise unsupported `supports`, `partial`, or `contradicts` label to `insufficient`. Correct numeric and evidence-ID citations remain valid. An unrecognized legacy ID can still recover via an exact quote in the shown pool. No new model or dependency is needed.

**Verification:** a red-first public `assess_claims_batch` test reproduced the wrong-source `supports` result; the existing resolver-level wrong-ID expectation was replaced with a red test for dropping a mismatched known ID and a legacy-ID recovery control. After the two-line resolver change, 39 batch/span/citation/provenance/freshness tests and 80 claim, gate, grounding, report and single-assessor tests passed. Ruff check and format passed. No provider request or additional cost. The original Qwen trial remains a failed frozen candidate; this code change is not a post-hoc pass or a model qualification.

**Disposition:** implemented locally; release verification remains in M11-OPS-02c4e4r.
