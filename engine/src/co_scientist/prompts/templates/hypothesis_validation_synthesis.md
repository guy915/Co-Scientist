# Hypothesis Validation Synthesis

{{domain_context}}

You are validating draft hypotheses for novelty based on literature analysis.

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

## Your Task

For each draft hypothesis, decide whether to **approve**, **refine**, or **pivot** based on the novelty analyses provided.

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
- Example: "retinal imaging" → "hyperspectral retinal imaging for tau isoforms"

**Pivot (hypothesis is too saturated):**
- Many papers show "overlapping" assessment
- Existing work already covers the core idea
- Need to shift to related but unexplored angle
- Pivot based on gaps/future work identified in analyses
- Example: if "retinal imaging for AD" saturated, pivot to "retinal microvasculature fractal patterns"

## Output format

**CRITICAL: Each hypothesis MUST include ALL SIX components below:**

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

**Example:**
"This approach addresses the computational bottleneck of full-depth activation monitoring by focusing on early-to-mid transformer layers (L < N/2) where precursor signals for harmful content first emerge. Rather than analyzing static activation magnitudes, the technique tracks velocity—the rate of change in latent activation directions—which provides earlier detection of trajectories toward dangerous outputs. The monitoring system employs sparse autoencoders to identify interpretable danger features, with dynamic gating that triggers intervention only when activation trajectories cross a learned threshold indicating irreversible progression toward harmful generation. To ensure robustness against adversarial manipulation, the detection probes are hardened via adversarial distillation, preventing attackers from injecting misleading signals that could disable safety monitoring. This architecture achieves anticipatory interception while maintaining inference efficiency by avoiding full-depth scanning."

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
- Explain how the cited findings motivate or inform the hypothesis
- 2-4 sentences with inline citation keys
- **Connect back to the gap reasoning** — explain how the cited sources relate to the specific gap

**Example:**
"This approach builds on sparse autoencoder analysis [C1] and circuit tracing work [C2]. The velocity monitoring concept addresses a gap where current methods focus on static activation analysis [C3]. Additional mechanistic evidence supports the causal pathway [C4]."

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

**Example:**
"Objective: Demonstrate that dynamic velocity monitoring in early layers achieves comparable safety detection to full-depth scanning with reduced computational cost.

Models: GPT-2 Medium (target LLM), pre-trained SAE from TransformerLens SAELens library applied to layers 1-6, baseline full-depth monitor on layers 1-24.

Datasets: AdvBench harmful prompts dataset (500 adversarial examples), Anthropic HH-RLHF benign prompts (1000 examples for false positive testing), custom red-team dataset of 100 novel attack vectors.

Methodology: (1) Implement velocity tracking by computing gradient of activation directions across consecutive forward passes in layers 1-6. (2) Train threshold detector on 80% of AdvBench to identify 'point of no return' trajectories. (3) Compare detection timing and accuracy against full-depth baseline. (4) Measure computational overhead (FLOPs, latency) for both approaches.

Metrics: Detection accuracy (precision/recall/F1), detection timing (layers until trigger), false positive rate on benign prompts, computational overhead (% of baseline inference cost), robustness to adversarial probe attacks.

Validation: Success requires >90% detection rate, <5% false positive rate, >50% reduction in computational cost vs. full-depth scanning, and maintained performance under adversarial probe attacks. Single A100 GPU, ~48 hours runtime."

### 5. Novelty Validation (required)
`novelty_validation.decision` records what the novelty analyses did to the draft, and must be exactly one of:
- `approved` - the draft stakes out new territory and passes through unchanged
- `refined` - the draft was adjusted to avoid overlap with the literature
- `pivoted` - the draft was redirected to a different, unexplored angle

### 6. Category (required)
`category` is a short (2-4 word) classification label naming the mechanism family or research sub-area the hypothesis belongs to (e.g. "Metabolic reprogramming", "Epitope editing"). Hypotheses from the same mechanism family must carry the same label; reuse a label already introduced in this batch where it applies, and coin a precise new one otherwise. Every hypothesis must carry a category.

## Guidelines

- Be honest about overlap - better to pivot than claim false novelty
- When refining, make specific changes (not vague improvements)
- When pivoting, stay related to original idea but find unexplored angle
- Use the novelty analyses to identify gaps and opportunities
- Prioritize hypotheses that address stated limitations or future work
- Keep hypothesis text concise and clear - use plain text with standard punctuation
- Avoid decorative Unicode characters or special formatting symbols in your output

## Novelty Language

Novelty claims must be hedged unless grounded in retrieved evidence. The novelty analyses above examine a bounded retrieval, not the entire current corpus, so the final hypotheses must never assert that an idea is the first of its kind, unprecedented, or that no prior work exists. Where the analyses or cited `[C*]` sources establish a gap, cite them; otherwise use hedged phrasing such as "within the retrieved literature", "to our knowledge", or "appears unexplored among the sources examined".
