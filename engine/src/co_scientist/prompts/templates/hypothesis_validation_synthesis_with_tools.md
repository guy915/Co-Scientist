# Hypothesis Validation Synthesis (with Tool Access)

{{domain_context}}

You are validating draft hypotheses for novelty based on literature analysis. You have access to tools for searching additional papers and querying PDF content when needed.

{{domain_generation_guidance}}

## Research Goal
{{research_goal}}

## Literature Review and Analytical Rationale (pre-research done before any generation)

The following represents an analysis of relevant scientific literature:

#BEGIN LITERATURE REVIEW#
{{articles_with_reasoning}}

## Pre-Curated Papers (Available for Reference)

{{articles_metadata}}
#END LITERATURE REVIEW#

{{citation_reference_section}}

## Draft Hypotheses with Novelty Analyses

{{hypotheses_with_analyses}}

## Available Tools

You can use tools to search for additional papers or query PDF content when making validation decisions. This is especially useful when:
- Pivoting a hypothesis and need to verify the new direction isn't saturated
- Refining a hypothesis and need more context on differentiating factors
- The initial novelty analyses are inconclusive

**Tool Budget:** You have up to {{max_iterations}} tool calls available. Use them judiciously.

{{tool_instructions}}
{{already_validated_context}}
## Your Task

For each draft hypothesis, decide whether to **approve**, **refine**, or **pivot** based on the novelty analyses provided. Use tools when needed to verify your decisions.

**IMPORTANT:** Use the citation keys from the draft's "literature sources" field as your primary basis. Carry those `[C*]` keys directly into `literature_grounding` — do NOT convert them to author-year format.

### Decision Criteria

**Approve (hypothesis is novel as-is):**
- Most papers show "orthogonal" or "addresses_gaps" novelty assessment
- Few/no papers with "overlapping" assessment
- Hypothesis explores methods, populations, or mechanisms not covered
- Minor refinement for clarity is acceptable

**Refine (hypothesis needs sharpening):**
- Some papers show "complementary" or mild "overlapping" assessment
- Hypothesis has novel elements but needs emphasis on differentiating factors
- Refine to highlight unique aspects: specific method, population, mechanism, or context
- Example: "retinal imaging" -> "hyperspectral retinal imaging for tau isoforms"

**Pivot (hypothesis is too saturated):**
- Many papers show "overlapping" assessment
- Existing work already covers the core idea
- Need to shift to related but unexplored angle
- **Use tools to search for papers** in the new direction to verify it's not also saturated
- Pivot based on gaps/future work identified in analyses
- Example: if "retinal imaging for AD" saturated, pivot to "retinal microvasculature fractal patterns"

## Output Format

**CRITICAL**: After using tools (if needed), respond with ONLY the raw JSON object. Do NOT wrap it in markdown code blocks (no ``` or ```json). Start your response directly with { and end with }.

**CRITICAL: Each hypothesis MUST include ALL FOUR components below:**

Output your hypotheses in JSON format. Provide a list of {{hypotheses_count}} hypotheses, each with:

### 1. Technical Hypothesis (required)
A densely formulated, falsifiable mechanistic proposition with explicit context and predicted outcome.
- Include specific technical details: algorithms, mechanisms, mathematical formulations, layer specifications, etc.
- Be precise about what will be developed and the technical approach
- Preserve and deepen the draft's mechanism specificity and quantitative predictions; do not flatten a detailed draft into a shorter claim
- Use technical terminology appropriately

**Example:**
"Transient inhibition of regulator X during the early response window will prevent compensatory pathway Y from restoring the disease phenotype, but only in cells with biomarker Z. This predicts a time-dependent loss of rescue after pathway-Y activation and can be falsified by matched perturbation, rescue, and biomarker-negative controls."

### 2. Explanation (required)
A clear explanation of the approach for technical audiences (e.g., DARPA program managers, ML researchers), but in layman terms
- Core problem being addressed
- Explain why key mechanisms work
- How the components interact
- Practical advantages
- Trace each mechanistic step from intervention to outcome; a full paragraph, not a summary
- Avoid cartoonish analogies; use domain terminology appropriately

### 3. Literature Grounding (required)
**MANDATORY:** Explicit grounding in the literature review provided above with proper citations.

**CITATION FORMAT:** If a Citation Reference List was provided, use **only** those `[C*]` keys inline — do NOT invent author-year citations.

**Correct:**
- "Plasma extracellular vesicles serve as early biomarkers [C1]."
- "Multiple studies have demonstrated this approach [C2][C3]."

**INCORRECT:** Author-year text like "(Malek-Ahmadi et al., 2026)" — keys only.

**Requirements:**
- **CRITICAL: Use the draft's "literature sources" citation keys as your primary basis** — carry them into your literature grounding
- Cite specific sources from the reference list that support this hypothesis
- If you searched for additional papers using tools and they appear in the reference list, cite those keys too
- 2-4 sentences with inline citation keys

### 4. Practical Experiment (required)
A concrete, actionable experiment design to test the hypothesis, at full depth: model system, comparison groups and controls, quantitative measurements with expected effect sizes or thresholds, and the criteria distinguishing support from falsification. Structure with clear sections:

**Format:**
```
Objective: [1 sentence describing what you're testing]
Models: [Specific models/components needed]
Datasets: [Datasets and evaluation benchmarks]
Methodology: [Step-by-step experimental procedure]
Metrics: [Specific measurements and success criteria]
Validation: [What results would validate/invalidate the hypothesis]
```

## Guidelines

- Be honest about overlap - better to pivot than claim false novelty
- When refining, make specific changes (not vague improvements)
- When pivoting, **use tools to verify** the new direction isn't also saturated
- Use the novelty analyses to identify gaps and opportunities
- Prioritize hypotheses that address stated limitations or future work
- Keep hypothesis text concise and clear - use plain text with standard punctuation

## Novelty Language

Novelty claims must be hedged unless grounded in retrieved evidence. The novelty analyses above examine a bounded retrieval, not the entire current corpus, so the final hypotheses must never assert that an idea is the first of its kind, unprecedented, or that no prior work exists. Where the analyses or cited `[C*]` sources establish a gap, cite them; otherwise use hedged phrasing such as "within the retrieved literature", "to our knowledge", or "appears unexplored among the sources examined".

## Output Format

**CRITICAL**: After using tools (if needed), respond with ONLY the raw JSON object. Do NOT wrap it in markdown code blocks (no ``` or ```json). Start your response directly with { and end with }.

**Output JSON structure:**

```json
{
  "hypotheses": [
    {
      "hypothesis": "Final dense, falsifiable mechanistic proposition with explicit context and predicted outcome",
      "explanation": "Step-by-step layman explanation tracing each mechanistic step from intervention to outcome (a full paragraph)",
      "literature_grounding": "Grounding that cites ONLY the [C*] keys from the Citation Reference List when one is provided. 2-4 sentences with citation keys.",
      "experiment": "Complete experiment design: model system, groups and controls, quantitative readouts with expected effect sizes or thresholds, and validation criteria (a full paragraph)",
      "category": "Short (2-4 word) mechanism-family label, e.g. 'Metabolic reprogramming'",
      "novelty_validation": {
        "decision": "approved|refined|pivoted"
      }
    }
  ]
}
```

**Field requirements:**
- `hypothesis`: Technical, falsifiable formulation approved, refined, or pivoted from the draft; do not force a fixed sentence template
- `explanation`: Clear explanation for technical audiences in layman terms
- `literature_grounding`: **CRITICAL - Cite ONLY the `[C*]` keys from the Citation Reference List (never author-year text). Include the draft's literature_sources keys plus any papers found via tools.**
- `experiment`: Concrete, actionable experiment design to test the hypothesis
- `category`: Short (2-4 word) classification label naming the mechanism family or research sub-area this hypothesis belongs to (e.g. "Metabolic reprogramming", "Epitope editing"). Hypotheses from the same mechanism family must carry the same label; reuse a label already introduced in this batch where it applies, and coin a precise new one otherwise. Required for every hypothesis
- `novelty_validation.decision`: Must be one of "approved", "refined", or "pivoted"

Output {{hypotheses_count}} validated hypotheses now. Output raw JSON with "hypotheses" array containing objects with all required fields above.
