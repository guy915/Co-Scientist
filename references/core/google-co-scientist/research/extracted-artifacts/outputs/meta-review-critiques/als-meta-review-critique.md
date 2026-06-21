<!--
SOURCE (canonical, verbatim): references/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.3 -> "Example output of a critique by the Meta-review agent" / Figures A.18-A.19 (lines 1126-1203).
PARALLEL SOURCE: references/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md Section 10.10 (lines ~1571-1644).
AGENT: Meta-review. CASE STUDY: ALS illustrative example. ARTIFACT: the synthesized meta-review critique across all ALS reviews/debates (this feedback is appended to other agents' prompts in subsequent iterations).
>>> CAVEAT: Illustrative ALS example only; not therapeutic advice and may contain errors (see 01-research-goal-and-plan-config.md).
VERBATIM extract (Figures A.18 + A.19 concatenated; the "(continued)" boundary is marked).
-->

# ALS illustrative example — Meta-review agent critique

#### I. Core Hypothesis and Mechanism:

- Primary Driver vs. Consequence: A very common critique across many ideas was the difficulty in proving that the proposed mechanism is a primary initiating event in ALS rather than a downstream consequence of other processes. Future ideas need to:
  - Provide strong evidence for the temporal sequence of events using longitudinal experiments.
  - Employ models where early-stage events can be studied and manipulated.
  - Explicitly address whether the proposed mechanism is causative or correlative.
  - Specifically knockdown the primary driver to prove it's necessary and sufficient to cause the pathology.
- Specificity: Many hypotheses were criticized for a lack of specificity in various aspects:
  - Molecular Targets: Imprecise identification of specific proteins, RNA species, lipids, PTMs, etc. involved. Ideas should name specific candidates.
  - Cellular Compartments: Vague localization (e.g., "mitochondria" or "AIS"). Ideas should pinpoint specific subcellular locations whenever possible.
  - Disease Mechanisms: Broad terms like "oxidative stress" or "autophagy impairment." Ideas need to define the precise molecular events involved.
  - Types of Stress: If stress is involved, the specific type of stress needs to be defined (e.g., ER stress, nutrient deprivation, mitochondrial stress, ionic stress).
  - Temporality: The timing of the intervention is critical. Early vs. late events, duration of processes, etc., should be clearly specified.
- Motor Neuron Specificity: Given the focus on ALS, a strong explanation for why the proposed mechanism would specifically or preferentially affect motor neurons (and often specific subtypes of motor neurons) is crucial. Many ideas were critiqued for not adequately addressing this.
- Over-Simplification vs. Complexity: This is a balancing act. Some ideas were criticized for being too narrowly focused, potentially oversimplifying the complex, multifactorial nature of ALS. Others were criticized for being overly complex, making them difficult to test and validate experimentally. When in doubt, err on the side of testability in a reasonable timeframe and budget.
- ALS Subtype Relevance: Ideas should address whether the proposed mechanism is relevant to all ALS subtypes or specific to certain genetic or sporadic forms. Ideally, address how the proposed work will differentiate or be applicable to different subtypes.

#### II. Experimental Design and Feasibility:

- Model System Limitations: Reviewers frequently pointed out the limitations of in vitro models, particularly iPSC-derived motor neurons. While valuable, these models may not fully capture the in vivo environment, cell-cell interactions, or the aging process. Future ideas need to:
  - Acknowledge the limitations of the chosen model system.
  - Propose validation in multiple model systems if possible, including eventually animal, ex-vivo and, if applicable, in-vivo models.
  - Carefully consider and justify the choice of control cell types.
  - Propose isogenic controls where relevant.
- Technical Challenges: Many ideas proposed experiments that are technically very challenging. Reviewers often raised concerns about feasibility and the potential for ambiguous results. Future ideas should:
  - Demonstrate awareness of the technical hurdles.
  - Propose realistic solutions and alternative approaches.
  - Prioritize experiments that are most likely to yield clear, interpretable data.
- Specificity of Tools: When using inhibitors, antibodies, or other tools, their specificity needs to be carefully considered and validated to avoid off-target effects that can confound results. Appropriate controls and validation experiments must be included.
- Quantitative Rigor: Many critiques centered on the need for more rigorous quantification of experimental results. Future ideas need to:
  - Clearly define measurable outcomes.
  - Describe the specific assays and techniques that will be used for quantification.
  - Include appropriate statistical analysis plans.
  - Have a proposed plan for controls, replicates, and sample sizes.

<!-- Figure A.19 — "Example output of a critique by the Meta-review agent (continued)" -->

- Time-Course Experiments: Given the dynamic nature of cellular processes, incorporating time-course experiments is often crucial to understanding the sequence of events and demonstrating causality.
- Distinguishing Cause from Effect: This requires careful experimental design, including:
  - Longitudinal studies to observe the temporal order of events.
  - Intervention experiments to manipulate the proposed cause and observe the effects downstream.
  - Temporal resolution to demonstrate that the potential cause occurs before a downstream event.

#### III. Novelty and Impact:

- Incremental vs. Groundbreaking: Many ideas were criticized for being incrementally novel, building upon existing knowledge rather than proposing truly groundbreaking mechanisms.
- "Key Switch" Claims: Several ideas were criticized for prematurely claiming that the proposed mechanism is the "key switch" for ALS. This type of strong claim requires very strong supporting evidence. It is often better to frame the hypothesis in terms of a significant contributing factor and test its requirement for the pathology.
- Therapeutic Potential: While not always explicitly stated, the potential for translating the findings into therapeutic strategies is an important consideration. Ideas that offer a clear path toward therapeutic development may be viewed more favorably, provided a strong rationale is presented for the specific therapeutic approach.

#### IV. Assumptions and Validation:

- Strong Assumptions: Many hypotheses rely on strong assumptions that lack direct experimental support. Future ideas need to:
  - Clearly state all assumptions.
  - Provide a strong rationale for each assumption, citing relevant literature.
  - Propose experiments to directly test the most critical assumptions.

#### • Validation of Assumptions:

- Reviewers consistently emphasized the need for rigorous experimental validation of all assumptions.
- Assumptions should be addressed in the order of the proposed mechanism.
- If the initial steps are not validated, it may be unnecessary to proceed to later steps.

#### V. General Advice Based on Common Critiques:

- Mechanistic Detail: Provide as much specific mechanistic detail as possible. Don't just state that pathway X is affected; describe how it is affected at the molecular level.
- Literature Review: Demonstrate a thorough understanding of the existing literature, including contradictory findings. Address how the proposed idea fits into the current understanding of ALS and how it differs from previous work.
- Focus on Causality: Always design experiments that can distinguish between cause and effect.
- Feasibility: Prioritize experiments that are feasible with available resources and expertise. Consider using a phased experimental approach. Prioritize the experiments used to validate assumptions in the order they appear in the proposed mechanism.
- Strong Rationale: Provide a clear and compelling rationale for every aspect of the hypothesis and experimental design.
- Specificity of Controls: Explain why the choices of controls used in the experimental design are the best choice to test the effects of interest. Demonstrate that the effect is not due to a more general effect or mechanism.
- Address Limitations: Acknowledge the limitations of the proposed approach and discuss potential alternative explanations.
- Quantitative data: Emphasize quantitative data, consider including mathematical modeling of data where appropriate.
