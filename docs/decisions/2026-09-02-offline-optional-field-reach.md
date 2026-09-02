# ADR: Which optional schema fields leave a renderer dark offline

**Status:** Accepted · 2026-09-02

`offline_schema_fill._fill_object` fills only a schema object's `required`
properties, so every property named in an `obj(..., optional=(...))` tuple is
absent from every offline response, always. This survey enumerates all such
properties across `engine/src/co_scientist/schemas/` and judges each: `dark`
if a real renderer or branch downstream only fires when the field is present
(so that path is unreachable on the offline backend), `harmless` if nothing
observable depends on it.

11 optional properties exist, at 8 declaration sites.

| Property | Schema (`name`) | What goes dark when absent | Verdict |
|---|---|---|---|
| `go_no_go_recommendation` | `full_review` (`FULL_REVIEW_SCHEMA`) | `VerdictLines`' "Verdict:" line, `ideas_detail_review_findings.tsx` (via `drain_reviews._verdict_detail`/`_review_detail_json`) | dark |
| `time_to_verdict` | `full_review` (same) | `VerdictLines`' "Time to verdict:" line, same chain | dark |
| `time_estimate` | `meta_review` (`META_REVIEW_SCHEMA`, `strategic_recommendations[]`) | `_render_recommendation`'s `(time_estimate)` suffix, `report_markdown_meta_review.py` | dark |
| `phase_label` | `meta_review` (same) | `_render_recommendation`'s `"{phase_label}: "` prefix | dark |
| `recommended_idea` | `meta_review` (same) | `_render_recommendation`'s "Recommended idea: …" line | dark |
| `comparative_notes` | `hypothesis_batch_review` (`REVIEW_BATCH_SCHEMA`) | Nothing — `review_helpers._review_from_response` never reads this key from the parsed response | harmless |
| `positive_observations` | `reflection_observations` (`REFLECTION_SCHEMA`) | `observation_feedback.apply_observation_result`'s "Confirmed strengths" block and `enrichments["observation"].positive_observations` — both real branches, but both feed only `reflection_notes`, which is read solely as ranking-prompt context; it is never persisted as a review row, never serialized to the app API, and never rendered in the frontend. No test, demo, or UI surface can observe the difference | harmless |
| `combined_partners` | `hypothesis_evolution` (`EVOLUTION_SCHEMA`) | `evolve_results._resolve_parents`/`_merged_partners` — a combination-operator child's multi-parent lineage | dark, left out |
| `example_hypothesis_indices` | `research_overview` (`RESEARCH_OVERVIEW_SCHEMA`, `research_contact_groups[]`) | `research_overview_contacts._resolve_example_hypothesis_ids` → `report_markdown_contact_groups.py`'s per-group example-hypothesis titles | dark, left out |
| `notes` | `research_overview_review` (`RESEARCH_OVERVIEW_REVIEW_SCHEMA`) | `research_overview_review._format_review_notes`/`_call_reviser` — the whole reject-and-revise branch | dark, left out |
| `evidence_id` | `research_overview_review` (`notes[]` items) | Same `_format_review_notes` `(evidence_id: …)` suffix | dark, left out |

**Totals:** 9 `dark`, 2 `harmless`. Dark and fixed in Part 2: the 5 `full_review`
and `meta_review` rows. Dark and left unfixed: the 4 rows below.

## Why the four remaining `dark` rows are left out

- **`combined_partners`** needs a value with particular structure: a 1-based
  index into *that call's* actual partner list. The generic filler's integer
  default (4) is essentially always out of range (`_partner_at` drops it), so
  reaching this branch needs a scalar-value override paired with the
  optional-fields hint, not a name list alone.
- **`example_hypothesis_indices`** has the same shape of problem: it needs a
  valid 1-based index into the run's actual top-k hypothesis list, which the
  schema filler has no way to know.
- **`notes`** and **`evidence_id`** (`research_overview_review`) are both
  blocked upstream of their own optionality: `accept` is *required* (not in
  this schema's `optional` tuple) and always fills to the generic boolean
  default `True`, so `_accepted()` never sees a rejection no matter what
  `notes` holds. Reaching `_call_reviser` would need a scalar-value override
  on `accept` too — which would make *every* offline research-overview call
  spend a second LLM call reviewing its own draft, a broader behavior change
  out of scope for a scoped, additive capability.

See `engine/src/co_scientist/offline_llm.py`'s `_OPTIONAL_FIELD_HINTS` for the
five rows (across the two `full_review`/`meta_review` schemas) this ADR marks
fixed.
