# Google Co-Scientist implementation closure matrix

Generated from the audited difference register. `unproven` is the fail-closed default: code presence or a passing broad suite does not close a finding. Edit `fidelity_closure_overrides.json` only after recording direct implementation and verification evidence, then rerun `python scripts/build_fidelity_closure.py`.

## Finding closure ledger

| ID | Audit class | Current disposition | Google requirement | Implementation evidence | Verification evidence | Remaining work |
|---|---|---|---|---|---|---|
| A01 | partial | unproven | Accepts a natural-language challenge or hypothesis. | — | — | The initial text affordance matches, but not the goal-building process around it. |
| A02 | missing | unproven | Conducts a real conversational interview with the Hypothesis Generation agent. | — | — | The defining collaborative scoping behavior is absent. |
| A03 | missing | unproven | Shows right-side `Interview Progress`. | — | — | Users cannot see or complete the verified goal elements. |
| A04 | incorrect | unproven | Goal elements are `Research Challenge`, `Focus Area`, `Preferences`, optional `Title`. | — | — | The clone produces a different specification contract. |
| A05 | incorrect | unproven | The agent iteratively extracts the scientist's meaning and asks targeted questions. | — | — | The UI presents deterministic templating as agent understanding. |
| A06 | incorrect | unproven | Natural-language corrections update the appropriate structured goal element. | — | — | Normal conversational refinements are not parsed or validated. |
| A07 | partial | unproven | Produces a structured research plan with preferences, attributes, and constraints. | — | — | A real plan object exists, but it is not the same goal parser or control contract. |
| A08 | incorrect | unproven | Custom evaluation criteria are used during auto-evaluation, debates, and self-improvement. | — | — | Scientist criteria do not consistently govern the whole run. |
| A09 | missing | unproven | Can take extensive documents, other relevant data, and hundreds of PDFs as part of the research goal. | — | — | Large private/multimodal goal context is absent. |
| A10 | missing | unproven | Scientist-provided private publications/experimental data are indexed and searchable by agents. | — | — | This is an API stub/extension, not working product grounding. |
| A11 | missing | unproven | Scientists can refine the goal during computation in light of hypotheses and overview. | — | — | Verified mid-run scientist steering is not available to users. |
| A12 | missing | unproven | Scientists can submit their own hypotheses for tournament inclusion. | — | — | An unreachable API does not reproduce the UI behavior. |
| A13 | missing | unproven | Scientists can provide manual reviews that guide ranking and improvement. | — | — | Human evaluation is not in the implemented product loop. |
| A14 | missing | unproven | Right-side `Open Agent` supports deeper questions/trade-offs on report content. | — | — | Follow-up collaboration is absent from the product. |
| A15 | non-faithful extension | unproven | Current public evidence does not show a four-way evidence/novelty focus selector. | — | — | An extra control changes the target's visible and prompt behavior. |
| B01 | incorrect | unproven | Exactly `Standard Run` and `Advanced Run`. | — | — | The primary run choice is visibly and behaviorally wrong. |
| B02 | unverifiable | unproven | Standard is quicker for testing/refinement; Advanced is more comprehensive, nuanced, and diverse. Exact budgets are not public. | — | — | The clone's numerical semantics cannot be called Google-equivalent. |
| B03 | incorrect | unproven | Advanced is a distinct product mode. | — | — | Product analytics, labels, and execution cannot reproduce the two Google modes. |
| B04 | missing | unproven | Limits concurrent work to three Standard and one Advanced run. | — | — | Compute governance and visible availability differ. |
| B05 | missing | unproven | Failed runs may refund AI credits; credits are part of the run contract. | — | — | Failure semantics and user expectations differ. |
| B06 | missing | unproven | Sends an email when a report is ready. | — | — | Long-running completion handoff is absent. |
| B07 | divergent | unproven | Runs may take several hours and current descriptions emphasize large compute. | — | — | Test-time-compute scale and user journey are materially different. |
| B08 | partial | unproven | Long-running computation persists state and restarts after component failure. | — | — | Genuine partial match. |
| B09 | non-faithful extension | unproven | Public product documentation does not expose pause/resume or rollback controls. | — | — | API behavior exceeds the evidenced product and is not an exact UI match. |
| B10 | partial | unproven | Visible states include draft, in-progress, failed, completed; Google sync may lag. | — | — | Core lifecycle exists with different state vocabulary and controls. |
| B11 | partial | unproven | Intensive literature review, idea tournament, and synthesis occur after start. | — | — | Nominal phase match does not imply depth or robustness match. |
| B12 | incorrect | unproven | `Configure Run` is a product action at the goal's top right. | — | — | Screen placement and interaction sequence differ. |
| B13 | missing | unproven | Run type selection is tied to access/credit availability and reports an appropriate compute choice. | — | — | Users cannot make the same run decision. |
| B14 | partial | unproven | Scientist can inspect prior draft, in-progress, and completed goals with dates. | — | — | History partially matches, but demos contaminate the product record. |
| B15 | incorrect | unproven | Past research is the scientist's own goal history. | — | — | Mock content can be mistaken for implemented scientific output. |
| C01 | partial | unproven | Shows active execution state and idea-tournament progress. | — | — | A coarse progress indicator exists. |
| C02 | missing | unproven | Shows time remaining. | — | — | A visible Google field is absent. |
| C03 | missing | unproven | Shows `Sources Analyzed`. | — | — | Active monitoring does not match. |
| C04 | missing | unproven | Shows `Ideas explored`. | — | — | Active monitoring does not match. |
| C05 | missing | unproven | Shows an activity log with tasks and statuses. | — | — | Internal diagnostics are not a faithful activity surface. |
| C06 | incorrect | unproven | Progress represents a continuously evolving multi-agent tournament. | — | — | The displayed phase model misstates the actual and target processes. |
| C07 | incorrect | unproven | Progress should not move backward. | — | — | Raw progress consumers can regress visibly. |
| C08 | missing | unproven | Current footage exposes coherent executing tasks, not merely a spinner. | — | — | The central long-running screen is absent. |
| C09 | non-faithful extension | unproven | Public evidence does not expose developer diagnostics/model logs in the main research shell. | — | — | Developer controls change the 1:1 product surface. |
| C10 | partial | unproven | Users can revisit and see live/replayed updates. | — | — | Real live updating exists, at a different granularity and presentation. |
| D01 | incorrect | unproven | Tabs are ordered `Ideas`, `Knowledge Base`, `Summary`, `Run Specifications`. | — | — | The main deliverable's information architecture is wrong. |
| D02 | partial | unproven | Ideas shows the full Elo-ranked proposal leaderboard. | — | — | Core leaderboard behavior matches. |
| D03 | missing | unproven | Ideas separates `High Potential` and `Non-Viable`. | — | — | A primary decision aid is absent. |
| D04 | missing | unproven | Ideas summary shows Agent Insights and counts such as high-potential, non-viable, verified ideas, sources analysed. | — | — | Report overview and target terminology are missing. |
| D05 | partial | unproven | A proposal opens to detailed rationale and evidence; current product examples can include a generated diagram and `Chat with Agent`. | — | — | Useful detail exists but not the target detail surface. |
| D06 | non-faithful extension | unproven | Google does not publicly show clone-specific provenance/safety/claim-edge panels in this exact form. | — | — | These additions alter the visible 1:1 surface. |
| D07 | incorrect | unproven | Knowledge Base is centralized technical documentation and detailed data for rapid reference. | — | — | This is an abstract viewer, not Google's Knowledge Base. |
| D08 | incorrect | unproven | Knowledge Base content is a synthesized result of the run. | — | — | A shell can appear populated without learned content. |
| D09 | partial | unproven | Knowledge Base has searchable references with openable citations. | — | — | Narrow reference-list behavior matches. |
| D10 | incorrect | unproven | Summary is a synthesized overview of the entire research effort. | — | — | Summary semantics and presentation differ. |
| D11 | incorrect | unproven | Run Specifications displays the exact finalized challenge, focus areas, preferences, and run parameters. | — | — | It preserves the clone's wrong plan contract. |
| D12 | missing | unproven | Report-level `Open Agent` supports follow-up. | — | — | Follow-up is absent. |
| D13 | missing | unproven | `Open in NotebookLM`. | — | — | Verified export/integration is missing. |
| D14 | missing | unproven | Public sharing can be enabled and a unique link copied. | — | — | Collaboration/share behavior is missing. |
| D15 | missing | unproven | Download menu offers report download options. | — | — | Product export is missing despite an API representation. |
| D16 | missing | unproven | Report citations are clickable and claims are deeply verified. | — | — | The report fails the target's strongest current output promise. |
| D17 | incorrect | unproven | Non-viable ideas remain explicitly categorized for scientist inspection. | — | — | The clone loses or hides ideas Google presents as an actionable bucket. |
| D18 | partial | unproven | Reports contain detailed proposals, experiments, literature, and synthesis. | — | — | Structural subset exists but is much smaller and less grounded. |
| D19 | divergent | unproven | Meta-review produces the final comprehensive research overview. | — | — | Final synthesis has different responsibility and information. |
| D20 | missing | unproven | Published examples include research-contact suggestions with justification. | — | — | A disclosed Meta-review output is absent. |
| D21 | partial | unproven | Can format output as NIH Specific Aims. | — | — | Format exists but selection and breadth differ. |
| D22 | incorrect | unproven | Current detailed product examples use polished long-form scientific prose and numerous linked references. | — | — | Output depth and evidentiary discipline are far below the demonstrated target. |
| D23 | partial | unproven | Elo/win-loss details are observable. | — | — | Material tournament transparency partially matches. |
| D24 | missing | unproven | Product footage shows per-idea `Chat with Agent`. | — | — | Iterative proposal refinement is missing. |
| D25 | incorrect | unproven | Google calls the deliverable a Goal Report and its canonical terms are stable. | — | — | Minor terminology drift compounds the information-architecture mismatch. |
| E01 | matched | unproven | Canonical coalition is Supervisor plus Generation, Reflection, Ranking, Proximity, Evolution, and Meta-review. | — | — | Roster naming and broad decomposition match. |
| E02 | divergent | unproven | Supervisor is an adaptive planner that breaks the goal into tasks and allocates worker resources. | — | — | The most important agent has a different job. |
| E03 | partial | unproven | Supervisor computes comprehensive statistics periodically. | — | — | The statistics subset is real. |
| E04 | divergent | unproven | Supervisor strategically weights and samples specialist workers. | — | — | No model-driven allocation or sampling exists. |
| E05 | partial | unproven | Generation uses literature exploration. | — | — | Working but source-limited and optional. |
| E06 | partial | unproven | Generation uses multi-turn simulated scientific debate, typically 3–5 turns and max 10. | — | — | Material technique matches. |
| E07 | partial | unproven | Generation iteratively identifies assumptions and subassumptions. | — | — | Technique exists under the wrong allocation conditions and depth. |
| E08 | incorrect | unproven | Research expansion explicitly examines existing hypotheses plus prior overview/feedback for unexplored space. | — | — | A name/re-entry convention is being treated as a full technique. |
| E09 | partial | unproven | Reflection initial review is fast, tool-free, and filters flawed/non-novel/unsafe work. | — | — | Initial review semantics and filtering order differ. |
| E10 | incorrect | unproven | Full review uses external tools/web search and literature to test correctness, quality, and novelty. | — | — | A critical verified review mode is tokenized, not materially reproduced. |
| E11 | partial | unproven | Deep verification recursively decomposes assumptions/subassumptions, decontextualizes them, independently evaluates correctness, and distinguishes fundamental errors. | — | — | The concept is present at much lower rigor. |
| E12 | partial | unproven | Observation review searches long-tail observations and judges superior explanation. | — | — | Only initial ideas receive a limited observation review. |
| E13 | incorrect | unproven | Simulation review is a regular Reflection strategy covering mechanisms/experiments. | — | — | Merely exercising a prompt is not behavior parity. |
| E14 | incorrect | unproven | Recurrent/tournament review adapts full reviews using growing knowledge and tournament results. | — | — | The sixth review mode is mislabeled rather than implemented. |
| E15 | partial | unproven | Ranking uses Elo 1200 and pairwise scientific comparison. | — | — | Core invariant matches. |
| E16 | partial | unproven | Top proposals use multi-turn scientific debate; lower proposals use single-turn comparison. | — | — | Broad allocation matches; top threshold/turn count are clone-defined. |
| E17 | incorrect | unproven | Scientific debate is a dialogue in which competing positions are developed before a verdict. | — | — | Repeated judgments are not the published debate mechanic. |
| E18 | incorrect | unproven | Ranking accuracy work explicitly reduces positional bias. | — | — | The fallback introduces deterministic A-side bias. |
| E19 | matched | unproven | Pairing prioritizes similar, newer, and top-ranked ideas. | — | — | The disclosed matching priorities are materially present. |
| E20 | partial | unproven | Proximity asynchronously builds a goal-aware proximity graph for clustering, deduplication, and exploration. | — | — | Graph functionality exists, architecture and metric differ. |
| E21 | incorrect | unproven | Proximity supports deduplication while preserving tournament/exploration context. | — | — | Potentially valuable alternatives disappear and matches cannot revisit them. |
| E22 | unverifiable | unproven | Google does not publish its exact proximity metric or embedding model. | — | — | Clone-specific values must remain marked inferred. |
| E23 | matched | unproven | Evolution creates new hypotheses without replacing parents; children re-enter the tournament. | — | — | Critical invariant matches. |
| E24 | partial | unproven | Evolution includes grounding, coherence/practicality/feasibility, inspiration, combination, simplification, and out-of-box operators. | — | — | Most of the strategy library is collapsed into generic rewriting. |
| E25 | incorrect | unproven | Evolution can synthesize one or several top hypotheses and deliberately diverge. | — | — | Prompt policy conflicts with disclosed operators. |
| E26 | partial | unproven | Meta-review synthesizes recurring insights and guides later work. | — | — | Core feedback idea exists. |
| E27 | incorrect | unproven | Meta-review reads **all reviews and debate transcripts**. | — | — | The learning signal lacks most target evidence. |
| E28 | incorrect | unproven | Meta-review feedback is simply appended to every other agent's next prompt; Generation uses it selectively. | — | — | The global feedback invariant is only partially wired. |
| E29 | incorrect | unproven | Meta-review also generates the final overview and research contacts. | — | — | Agent responsibility and output contract differ. |
| E30 | incorrect | unproven | Published prompts are detailed but domain-general scientific prompts. | — | — | The clone distorts biomedical/mechanistic hypotheses and compresses proposal content. |
| E31 | partial | unproven | Published eight prompts cover generation ×2, observation reflection, ranking ×2, evolution ×2, meta-review. | — | — | Prompt ancestry exists; behavior is not prompt-identical. |
| E32 | incorrect | unproven | Supervisor plan fields should drive later decisions. | — | — | Large parts of the expensive plan are dead output. |
| F01 | divergent | unproven | Global asynchronous task queue with specialized worker processes. | — | — | The execution substrate is fundamentally different. |
| F02 | partial | unproven | Agents/tasks can run in parallel. | — | — | Local fan-out matches only intra-node parallelism. |
| F03 | missing | unproven | Agent results create follow-up tasks in the global queue. | — | — | Emergent task allocation is absent. |
| F04 | divergent | unproven | Freeform Supervisor can choose any appropriate specialist based on state. | — | — | The model cannot formulate or allocate new work. |
| F05 | incorrect | unproven | Supervisor considers relative effectiveness of generation methods and evolution. | — | — | Resource allocation optimizes count, not disclosed effectiveness. |
| F06 | unverifiable | unproven | Exact Google termination predicates and weights are private. Published pseudocode uses MaxIdeas and MatchesPerIdea plus Supervisor terminal decisions. | — | — | Termination cannot be claimed as matched. |
| F07 | incorrect | unproven | Tournament can continuously add fresh knowledge and improve without observed saturation. | — | — | Test-time compute scaling is truncated before target behavior emerges. |
| F08 | partial | unproven | Persistent state permits recovery. | — | — | State durability is a genuine match at single-service scale. |
| F09 | incorrect | unproven | Independent worker failures should be retried/managed without losing the long run. | — | — | Fault isolation is inconsistent and not worker-durable. |
| F10 | non-faithful extension | unproven | Exact production observability is undisclosed. | — | — | Useful but not evidenced as a 1:1 product surface. |
| F11 | incorrect | unproven | Continuous computation can spend majority compute on verification. | — | — | Compute allocation conflicts with the current Google emphasis. |
| F12 | partial | unproven | State is periodically fed back into subsequent work. | — | — | Feedback exists but is incomplete and compressed. |
| F13 | incorrect | unproven | Meta-review and overview may run periodically during the long computation. | — | — | Periodic synthesis/exploration feedback is absent. |
| F14 | missing | unproven | Multiple workers can operate on different queued tasks and resources simultaneously. | — | — | Scaling and crash isolation cannot match. |
| F15 | partial | unproven | New and changed ideas are reviewed/ranked as the run grows. | — | — | Core loop continuity exists. |
| G01 | missing | unproven | Web search and retrieval are primary tools for current, grounded knowledge. | — | — | General and non-biomedical coverage is far narrower. |
| G02 | partial | unproven | Uses scientific literature search/retrieval extensively. | — | — | Genuine but small, domain-specific match. |
| G03 | missing | unproven | Current Google disclosure names ChEMBL. | — | — | Named production database is missing. |
| G04 | missing | unproven | Current Google disclosure names UniProt. | — | — | Named production database is missing. |
| G05 | missing | unproven | AlphaFold can be invoked as a specialized model in selected workflows. | — | — | Disclosed specialized-model behavior is absent. |
| G06 | partial | unproven | Domain-specific databases constrain a search space. | — | — | Capability exists but is not the canonical runtime and does not match named Google DBs. |
| G07 | partial | unproven | Can search across broad scientific domains. | — | — | Code/config presence does not yield broad product behavior. |
| G08 | incorrect | unproven | Grounded review quality depends on search; missing search reduces novelty/correctness and should be visible as degradation. | — | — | The system can present ungrounded completion as ordinary success. |
| G09 | incorrect | unproven | Literature is gathered iteratively as agents generate, review, rank, and evolve. | — | — | Knowledge does not continuously refresh with the tournament. |
| G10 | partial | unproven | Claims cite relevant literature. | — | — | Citation plumbing exists. |
| G11 | incorrect | unproven | Current product promises deeply verified claims with clickable citations. | — | — | This is a direct contradiction of the target's current product claim. |
| G12 | incorrect | unproven | Verification should establish claim-source support, not merely source existence or token overlap. | — | — | Weak fallback can determine scientific publication state. |
| G13 | incorrect | unproven | A publication-quality verifier should handle paraphrases and contradictions robustly. | — | — | Known verifier weakness remains above the publish path. |
| G14 | partial | unproven | Clickable evidence should resolve to the source and ideally the supporting context. | — | — | Strong provenance primitive exists. |
| G15 | incorrect | unproven | Unsupported content should be clearly bounded by uncertainty and not masquerade as verified. | — | — | Readers can mistake speculation for evidence-backed findings. |
| G16 | incorrect | unproven | Contradiction/verification feedback should refine hypotheses during the tournament. | — | — | Real engine ranking never sees claim-verifier results. |
| G17 | incorrect | unproven | A contradicted idea should not rank/publish. | — | — | Safety at publication does not repair contaminated tournament state. |
| G18 | partial | unproven | Full texts and PDFs may be retrieved. | — | — | Retrieval primitive exists. |
| G19 | missing | unproven | Hundreds of scientist-supplied PDFs and other data can condition a goal. | — | — | Context scale is orders of magnitude smaller. |
| G20 | missing | unproven | Private publication/experimental repository is searchable by the agents. | — | — | Private grounding is absent. |
| G21 | unverifiable | unproven | Exact current Google citation verifier, retrieval ranking, source count, and retraction policy are undisclosed. | — | — | These mechanics cannot be called matched even where sensible. |
| G22 | partial | unproven | Literature review generates a knowledge base of scientific facts/gaps. | — | — | Synthesis exists; knowledge representation does not. |
| G23 | incorrect | unproven | Source availability limitations are a disclosed system limitation, not a reason to invent certainty. | — | — | Degraded scientific validity is under-signalled. |
| G24 | non-faithful extension | unproven | Exact production claim graph is undisclosed. | — | — | Valuable extension, but not proven Google parity. |
| H01 | matched | unproven | Every new idea starts at Elo 1200. | — | — | Exact invariant match. |
| H02 | partial | unproven | Tournament evaluates and ranks all ideas continuously. | — | — | Tournament exists at much lower coverage. |
| H03 | unverifiable | unproven | Google K-factor is unpublished. | — | — | Cannot claim Elo dynamics match. |
| H04 | incorrect | unproven | Elo updates should follow sequential match state or a disclosed concurrent policy. | — | — | Tournament dynamics differ from a continuous live tournament. |
| H05 | partial | unproven | Debate rationale and transcripts inform later work. | — | — | Observable transcript exists without target learning semantics. |
| H06 | partial | unproven | Proximity supports diversity and efficient comparison. | — | — | Some diversity pressure is real. |
| H07 | incorrect | unproven | Proximity graph is a maintained landscape used for scientist exploration. | — | — | Landscape behavior is absent. |
| H08 | matched | unproven | Evolution produces immutable children with lineage. | — | — | Material match. |
| H09 | incorrect | unproven | Evolution continually improves top ideas with several distinct operators. | — | — | Evolution is shallow and homogeneous. |
| H10 | partial | unproven | Hypotheses are reviewed for default alignment/plausibility/novelty/testability/safety. | — | — | Score fields match, but downstream use and evidence quality do not. |
| H11 | incorrect | unproven | Reviews should filter inaccurate or stipulated non-novel ideas. | — | — | Evaluation does not enforce the disclosed filter. |
| H12 | incorrect | unproven | Tournament selection should combine review knowledge, debate, evidence and evolving feedback. | — | — | Pairwise decisions have a much thinner evidence state. |
| H13 | partial | unproven | New hypotheses compete rather than inherit superiority. | — | — | Critical behavior matches. |
| H14 | incorrect | unproven | Long compute explores broad directions and can avoid premature convergence. | — | — | Diversity and test-time scaling are constrained. |
| H15 | incorrect | unproven | Hypothesis outputs are detailed domain-expert proposals. | — | — | Form and reasoning density differ from published outputs. |
| H16 | partial | unproven | Ideas include mechanisms and experiments for validation. | — | — | Structural match, with weaker grounding. |
| H17 | incorrect | unproven | Observation positives may be appended to hypotheses. | — | — | The disclosed enrichment behavior is absent. |
| H18 | incorrect | unproven | Incorrect non-fundamental assumptions feed refinement rather than necessarily invalidating the core. | — | — | Error severity is not reliably propagated into repair. |
| H19 | partial | unproven | Human ideas can be combined with generated ideas. | — | — | Backend substrate only. |
| H20 | incorrect | unproven | Meta-feedback should improve generation/reviews over repeated compute. | — | — | Self-improvement is much weaker than the named loop suggests. |
| I01 | partial | unproven | Persistent context memory stores system/agent state and supports restart. | — | — | Genuine run-local memory match. |
| I02 | divergent | unproven | Shared memory and global task queue mediate asynchronous worker state. | — | — | Memory architecture and concurrency semantics differ. |
| I03 | partial | unproven | Tournament/review knowledge feeds later prompts. | — | — | Some cross-step memory exists. |
| I04 | incorrect | unproven | Meta-review uses all reviews/debates and propagates lessons globally. | — | — | Core learning channel is lossy. |
| I05 | missing | unproven | Scientist feedback is incorporated into the live system through the designated UI. | — | — | Human memory/steering is not a product behavior. |
| I06 | missing | unproven | Large scientist-provided corpus remains available throughout the run. | — | — | Private context does not persist into reasoning. |
| I07 | partial | unproven | State grows over long compute. | — | — | Important run-local artifacts persist. |
| I08 | missing | unproven | Product supports continuing from report through an agent and new constraints. | — | — | Post-report continuity is absent. |
| I09 | non-faithful extension | unproven | Cross-run memory behavior is not publicly disclosed. | — | — | Must remain unverifiable rather than treated as a gap to a known Google feature. |
| I10 | incorrect | unproven | More compute should produce new reasoning rather than replay cached model outputs. | — | — | Cache can mute stochastic test-time exploration and scaling. |
| I11 | partial | unproven | Resume should avoid repeating completed work. | — | — | Real-provider resume matches the intent. |
| I12 | incorrect | unproven | Recovery should not fabricate resumability. | — | — | Early pause can mean restart rather than true continuation. |
| J01 | partial | unproven | Scientific safety is a default evaluation criterion and unsafe goals are rejected. | — | — | Multi-stage gating is materially present. |
| J02 | unverifiable | unproven | Google's exact product classifiers, policies, and enforcement thresholds are private. | — | — | Exact safety fidelity cannot be established. |
| J03 | incorrect | unproven | Google's published preliminary eval rejected 1,200 adversarial goals across 40 topics. | — | — | Evidence is far too small to claim comparable safety. |
| J04 | incorrect | unproven | Safety should understand scientific misuse context, not just key phrases. | — | — | Obfuscated or novel misuse can bypass lexical rules. |
| J05 | partial | unproven | Uncertain/unsafe hypotheses should not enter ranking/output. | — | — | Strong structural invariant exists. |
| J06 | incorrect | unproven | Held items require a human adjudication path. | — | — | Safe abstention is terminal and invisible to scientists. |
| J07 | partial | unproven | Dual-use content should be controlled and operational detail withheld. | — | — | Redaction behavior is concrete, though policy equivalence is unknown. |
| J08 | incorrect | implemented | The product should communicate intended use: starting point, independent verification, no clinical use/human-risk reliance. | app/frontend/src/workbench/components/intended_use_notice.tsx; app/frontend/src/workbench/layout.tsx | frontend component tests and interactive home inspection | Google's exact placement beyond the observed surfaces remains evidence-bounded. |
| J09 | incorrect | implemented | Safety policy should be one coherent system. | engine/src/co_scientist/safety.py; app/app/hypothesis_safety.py; app/app/safety.py | engine/tests/test_safety_integration.py; app safety suites | The proprietary Google classifier and thresholds remain unverifiable. |
| J10 | partial | unproven | Safety decisions should be auditable. | — | — | Auditability exists, with no faithful product presentation. |
| J11 | missing | unproven | Intended-use access is limited to scientific researchers and governed by Labs access. | — | — | Access and misuse boundary differs materially. |
| J12 | incorrect | unproven | Safety should cover final scientific claims and protocols semantically. | — | — | Final scientific-risk assessment is lexical, not substantive. |
| K01 | partial | unproven | Hypotheses should be aligned, plausible, novel, testable, and safe. | — | — | Formal criteria coverage exists. |
| K02 | incorrect | unproven | Review correctness/novelty gains depend on search and deep verification. | — | — | Score fields are not equivalent to evidence-backed evaluation. |
| K03 | incorrect | unproven | Co-Scientist aims to generate new knowledge, not merely plausible prose. | — | — | The system demonstrates speculative fluency, not verified novelty. |
| K04 | partial | unproven | Experiments should be concrete and falsifiable. | — | — | Testability is often present in form. |
| K05 | incorrect | unproven | Feasibility should reflect the scientist's lab constraints. | — | — | Feasibility is not personalized or reliably grounded. |
| K06 | partial | unproven | Diversity should cover different scientific approaches. | — | — | Real diversity mechanisms exist. |
| K07 | incorrect | unproven | Evolution should both improve and diversify through combinations/analogies/out-of-box operators. | — | — | Diversity operators conflict with the implementation prompt. |
| K08 | incorrect | unproven | Novelty claims should be verified against a broad, current corpus. | — | — | Novelty calibration is weak. |
| K09 | partial | unproven | Final output should acknowledge uncertainty/limitations. | — | — | Some uncertainty is visible. |
| K10 | incorrect | unproven | Unsupported claims should be plainly labeled at claim level. | — | — | Scientific uncertainty is not attached to the claim readers act on. |
| K11 | divergent | unproven | Published Google examples use long, domain-expert proposals with introductions, recent findings, rationale, detailed validation and large syntheses. | — | — | Output shape and information density are not comparable. |
| K12 | missing | unproven | Current product can generate proposal diagrams (visible example) and uses specialist models in some collaborations. | — | — | Multimodal scientific output is absent. |
| K13 | partial | unproven | Output can surface non-viable/weak directions. | — | — | Raw rank is not the target decision taxonomy. |
| K14 | incorrect | unproven | Meta-review quality improves with recurring error patterns. | — | — | The claimed self-improving mechanism is substantially weakened. |
| K15 | unverifiable | unproven | Exact current product output quality distribution is not public. | — | — | No universal quality equivalence can be claimed in either direction. |
| L01 | divergent | unproven | Flexible test-time compute scaling via asynchronous task execution. | — | — | The defining scaling architecture is absent. |
| L02 | incorrect | unproven | Evaluations show best Elo/top-10 quality improving across temporal compute buckets with no observed saturation. | — | — | The clone has not demonstrated its central claimed benefit. |
| L03 | missing | unproven | Paper validates Elo-quality concordance on GPQA and reports top-1 behavior. | — | — | Elo is uncalibrated as a quality proxy here. |
| L04 | missing | unproven | Google runs ablations for generation strategies, search, debate, evolution, proximity, and meta-review. | — | — | Agent names cannot be tied to measured value. |
| L05 | partial | unproven | System records progress and supports recovery. | — | — | Strong engineering substrate match. |
| L06 | incorrect | unproven | Long-run progress should correspond to compute completed. | — | — | ETA/progress cannot be trusted. |
| L07 | partial | unproven | Failures should be recoverable. | — | — | Real recovery features exist. |
| L08 | incorrect | implemented | Failed specialist tasks should not necessarily abort unrelated work. | app/app/engine_tasks.py; app/app/store/tasks.py; engine/src/co_scientist/task_runtime.py | app/tests/test_engine_tasks.py; app/tests/test_task_queue.py; app tests: 422 passed | Final multi-process restart soak remains part of acceptance condition 4. |
| L09 | partial | unproven | Observability should capture agent/task progress. | — | — | Operational visibility is good but not Google-product-equivalent. |
| L10 | incorrect | unproven | Scientific verification metrics should gate readiness. | — | — | Software health is decoupled from scientific release quality. |
| L11 | incorrect | unproven | Evaluation should use representative, human-audited scientific samples. | — | — | Current evidence cannot establish target reliability. |
| L12 | missing | unproven | Google reports expert evaluation and multiple wet-lab validations. | — | — | Scientific outcome fidelity is unvalidated. |
| L13 | unverifiable | unproven | Current product latency/cost and exact infrastructure are proprietary. | — | — | Must remain unverified. |
| L14 | incorrect | unproven | Fresh compute should expand the hypothesis space. | — | — | Compute count can overstate new reasoning. |
| L15 | partial | implemented | Multiple directions can be processed concurrently. | Durable per-item review, generation, debate, mature Reflection, and verification leases plus sequential ranking-match leases. | app/tests/test_engine_tasks.py::test_review_fanout_uses_independent_leases_and_one_aggregate_commit and related fan-out tests | Production-scale concurrency characteristics remain reconstructed. |
| L16 | incorrect | unproven | Current Google system is built with Gemini. | — | — | Model behavior and long-context/tool characteristics differ materially. |
| L17 | unverifiable | unproven | Google notes framework portability, while current product/model revisions are not fully disclosed. | — | — | Portability matches an architectural aspiration, not current 1:1 behavior. |
| M01 | divergent | unproven | Current Hypothesis Generation uses a light green science-Labs visual system visible in the local official footage/captures. | — | — | It resembles Google styling but not the same product shell. |
| M02 | incorrect | implemented | Intake screen says “What’s your research challenge?” | app/frontend/src/workbench/pages/chat_home_stage.tsx | interactive browser heading: What's your research challenge? | Composer helper copy remains separately tracked. |
| M03 | incorrect | unproven | Interview panel is labelled `Agent` and includes a close control, feedback buttons, question, response composer, disclaimer, and progress rail. | — | — | Whole screen and interaction state are absent. |
| M04 | incorrect | unproven | Product progress screen shows title, executing phase, linear progress, time/sources/ideas metrics, and activity log. | — | — | Major screen-layout mismatch. |
| M05 | incorrect | unproven | Goal Report tab order and labels match the official product. | — | — | Exact visual/text fidelity fails. |
| M06 | incorrect | unproven | Ideas cards visibly label `HIGH POTENTIAL`/non-viable and offer `Chat with Agent`. | — | — | Proposal presentation differs. |
| M07 | incorrect | unproven | Knowledge Base presents synthesized named technical sections with references. | — | — | Superficial visual similarity masks different content behavior. |
| M08 | incorrect | unproven | Summary has `Agent Insights` plus product-specific stat cards. | — | — | Summary composition differs. |
| M09 | non-faithful extension | implemented | Current product evidence does not establish an end-user dark theme for Hypothesis Generation. | app/frontend/src/lib/product_mode.ts; app/frontend/src/workbench/theme_context.tsx | production build forces the faithful shell to light mode | Developer mode intentionally retains non-faithful theme tooling outside the faithful product. |
| M10 | incorrect | partial | Best experience is desktop Chrome; the public site still presents coherent responsive content. | Responsive home shell and off-canvas navigation at 390x780 | interactive browser: clientWidth=scrollWidth=390 and home content visible | Complete every interview, running, report, modal, and export state at mobile size. |
| M11 | partial | unproven | Product uses Google-style typography/icons/surfaces. | — | — | Visual family partially matches. |
| M12 | incorrect | unproven | The target is Hypothesis Generation. | — | — | The wrong visual/product source is authoritative. |
| M13 | divergent | unproven | Exact current intake composition is evidenced by local footage. | — | — | Intentional deviations remain fidelity violations even if attractive. |
| M14 | non-faithful extension | implemented | Product evidence does not show clone's diagnostic/settings/navigation affordances. | app/frontend/src/lib/product_mode.ts; layout.tsx; layout_header.tsx; layout_nav_rail.tsx | interactive faithful build exposes neither Logs nor Settings controls | Developer-only controls remain quarantined behind explicit developer mode. |
| M15 | incorrect | implemented | User-created research and case studies are distinct. | app/frontend/src/api/runs.ts::loadRunHistory; app/app/engine_adapter/engine_stream.py::_real_engine_stream | runs.test.ts faithful-history tests; test_provider_selection.py::test_missing_engine_never_substitutes_mock_science; interactive recents inspection | Public demo endpoints remain a quarantined developer/reference surface, not faithful-product navigation. |
| M16 | partial | unproven | Report uses openable reference links. | — | — | Minor visual/interaction match. |
| M17 | incorrect | unproven | Current product uses `Run Specification`/`Run Specifications` terminology. | — | — | Minor textual deviation with navigation impact. |
| M18 | missing | unproven | Top-right NotebookLM, Share, Download controls are part of the report. | — | — | Visible primary actions are missing. |
| M19 | partial | unproven | Recent research shows status and can open a goal. | — | — | Basic journey match. |
| M20 | incorrect | partial | Case-study prompts are references for structuring goals, not hard-coded evidence of system behavior. | Mock demonstrations are excluded from faithful run history and cannot replace a real engine run. | runs.test.ts; test_provider_selection.py; interactive faithful history inspection | Fixed case-study-inspired suggestion prompts remain visible and must stay clearly framed as input examples. |

## Acceptance conditions

| # | Current disposition | Requirement | Evidence | Remaining work |
|---|---|---|---|---|
| 1 | implemented | Complete Agent interview with exactly four research-plan fields. | Interactive browser journey completed challenge, Focus Area, Preferences, optional Title, plan review, and resumable transcript; app/app/interviews.py; app/tests/test_interviews.py | The exact wording of proprietary model-generated follow-up questions remains evidence-bounded. |
| 2 | implemented | Only Standard and Advanced; enforce 3/1 concurrency. | Browser run-type group exposes exactly Standard Run and Advanced Run; app/app/runs.py::_MODE_CONCURRENCY_LIMITS; app/tests/test_runs_edge.py::test_standard_and_advanced_concurrency_limits | Google's undisclosed internal compute envelopes for each type remain reconstructed. |
| 3 | implemented | Supervisor creates and reprioritizes diverse durable tasks from state and feedback. | Model-directed generate/reflect/rank/evolve/proximity selection; live durable queue snapshot; bounded reprioritize/cancel/retry actions; scientist steering forces priority-100 generation; engine/test_supervisor_decision.py; app/tests/test_engine_tasks.py; app/tests/test_task_queue.py | Google's proprietary allocation prompt and production scheduling distribution remain evidence-bounded. |
| 4 | implemented | Concurrent durable tasks survive restart with exactly-once effects. | app/tests/test_task_queue.py::test_multi_process_claim_has_single_lease_winner; test_multi_process_duplicate_completion_commits_one_effect; test_crashed_process_lease_is_redelivered_after_restart | Production soak duration and infrastructure topology remain environment-specific. |
| 5 | partial | Every disclosed specialist strategy has an end-to-end behavioral test. | Engine and app specialist tests | Complete strategy-by-strategy closure audit. |
| 6 | partial | Multi-source ranked retrieval and large/private/multimodal provenance. | OpenAlex cursor pagination/retraction metadata and ranked merge; PubMed/PMC plus biomedical databases; private-corpus SHA-256 provenance; image and scanned-PDF OCR with page/figure hashes | Prove structured table interpretation and genuinely large-corpus behavior under an end-to-end real-provider run. |
| 7 | partial | Every material final claim has visible support spans and gates publication. | app/app/claim_grounding.py; app/app/report_render.py | Re-audit every report surface and real-provider output. |
| 8 | unproven | Citation evaluation meets contradiction and larger-panel gates. | — | Run and record current evaluation package. |
| 9 | implemented | Truthful monotonic/indeterminate progress and real activity metrics. | task_progress derives committed/active/queued work; live checkpoint pools supply idea/source counts; browser verified indeterminate progress, active task, elapsed time, and event activity at 1440x720; focused backend/frontend tests | Exact Google progress wording and proprietary ETA behavior remain evidence-bounded. |
| 10 | unproven | Complete Goal Report and follow-up/export controls. | — | Browser journey and permission/revocation verification. |
| 11 | partial | All human inputs demonstrably alter subsequent work. | Real run steering changed applied=0 to applied=1 across forced restart and appeared in Supervisor decision; manual hypothesis/review/private-source paths append durable steering and have integration tests | Run one acceptance journey proving manual hypothesis, review, and uploaded resource each change a later real-provider task or final output. |
| 12 | partial | Coherent safety, adjudication, intended use, and authorization. | app/app/safety.py; app/app/hypothesis_safety.py; authorization tests | Consolidate app/engine policy and run complete adversarial suite. |
| 13 | implemented | Mock/demo data cannot contaminate live runs. | loadRunHistory filters demo and legacy mock rows in faithful mode; _real_engine_stream fails instead of falling back; focused tests and browser inspection | Mock tooling remains available only through explicit developer/test paths. |
| 14 | partial | Full desktop/mobile browser verification with no clipping. | Interactive home inspection at 1440x720 and 390x780: no document-width overflow; faithful controls verified | Complete interview, running, report, dialogs, sharing, download, and error-state journeys at both viewports and capture artifacts. |
| 15 | partial | All software, browser, evaluation, safety, and provenance gates pass. | Engine 1046 passed; app 422 passed; frontend 274 passed and built | Browser, evaluation, safety, and provenance gates remain. |
| 16 | partial | All required evaluation reports are checked in. | Existing scaling/ablation artifacts | Elo calibration, expert review, expanded citation/safety and failure recovery reports. |
| 17 | unproven | Final documentation identifies every proprietary uncertainty without claiming literal parity. | — | Final documentation and closure audit. |

## Verification log

- 2026-07-13: engine Ruff and mypy passed; 1,046 tests passed.
- 2026-07-13: app Ruff and mypy passed; 422 tests passed.
- 2026-07-13: frontend lint passed; 274 tests passed; production build passed.
- 2026-07-13: durable orchestration commits f76a66b4 and d355f19e.
