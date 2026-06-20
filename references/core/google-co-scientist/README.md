# AI Co-Scientist Clone — Consolidated Specification

This is a consolidation of the project's 26 research/blueprint documents into **9 grouped reference files**, with redundancy and duplication resolved. Each file owns one engineering concern and cross-references the others rather than repeating shared material.

## The nine files

| # | File | Owns | Read it for |
|---|---|---|---|
| 01 | **Source System Reference** | the canonical ground truth | what DeepMind's system actually does; the 3 fidelity invariants; the glossary |
| 02 | **Product Surface and UX** | the visible product | user journey, 4-tab report, IA, control console, Material 3 design, MVP roadmap |
| 03 | **System Architecture and Orchestration** | the backend | 8-stage loop, LangGraph+Temporal, monorepo, Postgres schema, API/event contract, ResearchLoop control plane, MCP |
| 04 | **Agent Coalition Specifications** | the 12 agents | per-agent role/IO/model/tools; NIH output structure; agent-layer fidelity checklist |
| 05 | **Tournament, Evolution & Evaluation Criteria** | generate→debate→evolve | Elo math, 3-persona debate, evolution operators, domain rubrics, discovery heuristics |
| 06 | **Retrieval, Grounding & Verification** | scientific grounding | DB sources + rate limits, hybrid search, knowledge graph + evidence math, citation verification, GRADE, safety pipeline |
| 07 | **Context Engineering and Memory** | staying coherent | layered memory, KSDS blackboard, E-mem, compaction, self-optimizing prompts, SQLite schema |
| 08 | **Prompting Architecture & Prompt Library** | language | style rules, epistemic taxonomy, per-agent personas, full prompt library (paper + golden + Jinja) |
| 09 | **Build Methodology, Landscape & Fidelity** | building & proving it | Claude Code harness, open-source fork/mine/reject, precedents, 9-category fidelity harness, BRIDGE, M2M, phased build |

## Source-document → consolidated-file mapping

- **01** ← Towards_an_AI_co-scientist; Accelerating_scientific_discovery_with_Co-Scientist
- **02** ← DeepMind_Co-Scientist_Product_Surface_Research_Report; Product_Information_Architecture_and_Interaction_Blueprint; UX_Design_Spec_for_High-Fidelity_Co-Scientist_Clone; Co-Scientist_MVP_Product_Scope_and_Development_Roadmap (+ M3 design from Technical_Architecture_and_Product_Specification_Blueprint)
- **03** ← AI_Co-Scientist_Systems_Architecture_and_Technical_Spec; Technical_Architecture_and_Product_Specification_Blueprint; Technical_Analysis_and_Implementation_Blueprint_for_a_1_1_…; Open-Source_Co-Scientist_Clone_Architecture_and_Implementation_Plan; Autonomous_Multi-Agent_Scientific_Discovery_Blueprint; Interactive_Multi-Agent_Scientific_Discovery_Platform_Blueprint; Stateful_Agentic_Runtime_and_Orchestration_Blueprint; Distributed_Multi-Agent_Discovery_Harness_Technical_Spec
- **04** ← agent-roster sections of AI_Co-Scientist_Systems_Architecture…; Autonomous_Multi-Agent…; Interactive_Multi-Agent…; Stateful_Agentic_Runtime…; Multi-Agent_Hypothesis_Generation_Tournament_Architecture; Systems_Design_Multi-Agent_Orchestration_and_Claim_Verification
- **05** ← Hypothesis_Generation_Evaluation_and_Tournament_Specs; Multi-Agent_Hypothesis_Generation_Tournament_Architecture (+ tournament/evolution sections across docs)
- **06** ← Scientific_Retrieval_and_Verification_Layer_Architecture; Knowledge_and_Evidence_Graph_Layer_Architecture; Systems_Design_Multi-Agent_Orchestration_and_Claim_Verification (+ grounding/safety sections across docs)
- **07** ← Context_Engineering_and_Stateful_Memory_Architecture; Context_Engineering_Spec_for_Multi-Agent_Co-Scientist (+ memory/state from Stateful_Agentic_Runtime…)
- **08** ← Linguistic_and_Prompting_Architecture_for_Agent_Discovery; appendix prompts from Towards_an_AI_co-scientist; golden prompts from Co-Scientist_Engineering_Blueprint…; Jinja templates from Context_Engineering_and_Stateful_Memory_Architecture
- **09** ← Agentic_Development_Harness_for_Co-Scientist_Clone; AI_Co-Scientist_Landscape_Analysis_and_Cloning_Guide; Engineering_Precedents_for_Agentic_Scientific_Discovery; Co-Scientist_Engineering_Blueprint_and_Fidelity_Evaluation (+ fidelity sections across docs)

*(The project's own `CLAUDE.md` and `README.md` were excluded from consolidation, as requested.)*
