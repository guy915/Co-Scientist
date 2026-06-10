# 02 — Product Surface and UX

> **Purpose.** Defines the *visible product* the clone must reproduce: the user-facing flow, screen inventory, interaction model, visual design system, and the MVP scope/roadmap. The behavioral/agentic internals live in files `03`–`08`; this document is about what the scientist sees and does.
>
> Consolidates: `DeepMind_Co-Scientist_Product_Surface_Research_Report.md`, `Product_Information_Architecture_and_Interaction_Blueprint.md`, `UX_Design_Spec_for_High-Fidelity_Co-Scientist_Clone.md` (UX portions), `Co-Scientist_MVP_Product_Scope_and_Development_Roadmap.md`, plus the Material 3 visual-design portions of `Technical_Architecture_and_Product_Specification_Blueprint.md`.

---

## 1. The target product: Google's "Hypothesis Generation / Gemini for Science"

The public product surface (marketed as **Hypothesis Generation**, via Google Labs, desktop + Chrome) follows a single end-to-end journey:

```text
SIGN UP → GOAL SETUP → INTERVIEW → RUN EXECUTION → REPORT REVIEW → EXPORT/SHARE → FOLLOW-UP
(Labs)    (prompt)     (scoping)    (Std/Adv)        (4-tab report)  (NotebookLM/dl)  (iterate)
```

Four interface principles run through it:

1. **Natural-language first** — the primary interface is conversational, not form-based ("just like talking to a colleague").
2. **Scientist-in-the-loop** — humans steer direction and validate outputs.
3. **Transparent process** — users can see tournament rankings, debate transcripts, and idea evolution.
4. **Iterative** — designed for multiple cycles, not one-shot generation.

---

## 2. The core user journey, stage by stage

### Stage 1 — Research-goal setup
The user enters a high-level goal in natural language (e.g. *"How would you approach epigenomic aspects of liver fibrosis and what drugs could you use to treat it?"*). The Supervisor parses the goal into a research plan configuration. Goal input supports typing, voice/speech-to-text, document upload (drag-drop), and template selection.

### Stage 2 — Interview-style refinement
After initial entry, the system runs a **conversational interview** (the Intake/Interview agent) to scope the goal. It clarifies the specific question, hypotheses to explore, focus areas, constraints (ethical/technical/resource), and output preferences (e.g. NIH format). It asks **clear, singular** clarifying questions and shows a live, structured research-plan summary the user can edit/approve.

Example interview turn:
```text
User: "Find epigenetic targets for liver fibrosis."
Intake: "Understood. Let us scope this challenge:
1. Are you focusing on specific epigenetic classes (e.g., histone methyltransferases, HDACs)?
2. Do you have preferred model systems for downstream validation (e.g., human hepatic organoids)?
3. Should we exclude compounds with known cardiotoxicity profiles?"
```

### Stage 3 — Run configuration (Standard vs Advanced)
Accessed via **"Configure Run"** (top-right of the goal interface).

| Run Type | Purpose | Characteristics |
|---|---|---|
| **Standard Run** | Testing/refining research goals | Quicker results; optimized for speed; shallow search; smaller tournament pool; constrained debate iterations; ~2 evolutionary cycles |
| **Advanced Run** | Comprehensive analysis for breakthroughs | Deeper, more nuanced/diverse suggestions; deep databases; extensive pairwise tournaments; ≥10 evolutionary iterations; deep verification + simulated validation |

Open-source implementations expose additional config: LLM model selection, number of hypotheses (typically 20–30 in tournament; 50+ for advanced), temperature, test-time-compute scaling, agent on/off toggles + weights, knowledge-base/database selection, citation recency, output format (NIH Specific Aims, standard proposal), detail level, and notification settings. The confirmation panel summarizes config + estimated time/cost.

### Stage 4 — Active run monitoring
Real-time visibility into multi-agent execution, with:

- **Progress dashboard** — overall progress bar, estimated time remaining, agent activity status.
- **Agent activity panel** — live view of which agent is active and its current sub-task (Generation creating, Reflection critiquing, Ranking running tournaments, Evolution refining, Meta-review synthesizing).
- **Live log stream** — real-time agent actions.
- **Knowledge-base growth** — accumulating reference count.
- **Tournament visualization** — Elo changes, head-to-head results, debate transcripts (bracket view / Elo-over-time chart / head-to-head).
- **Intervention points** — add feedback mid-run, pause/resume, provide context, early-terminate with partial results.

The run is a **state machine**: `Draft → Configuring → Queued → Initializing → Running → Paused → Completed/Failed`.

### Stage 5 — The Goal Report (4 tabs)
The deliverable is a **Goal Report** with four tabs:

```text
┌──────────────────────────── GOAL REPORT ─────────────────────────────┐
│   IDEAS        │  KNOWLEDGE     │   SUMMARY     │  RUN SPECIFICATIONS  │
│ (Leaderboard)  │     BASE       │               │                      │
└────────────────┴────────────────┴───────────────┴──────────────────────┘
```

1. **Ideas (Leaderboard)** — full ranked list of generated proposals from the tournament, each with supporting rationale, Elo score, novelty assessment, confidence. Includes tournament viewer, debate transcripts, win-loss stats, hypothesis-evolution view.
2. **Knowledge Base** — centralized repository of in-depth technical documentation, research-backed insights, and literature synthesis. May include a knowledge graph (papers/concepts/hypotheses), semantic search, document viewer, citation context, evidence table.
3. **Summary** — synthesized high-level overview of the entire effort: goal recap, key findings, recommended next steps, limitations/non-viable directions identified.
4. **Run Specifications** — parameters and constraints that defined the run (the config used).

### Stage 6 — Sharing, export, continuation
- **NotebookLM integration** — export results directly to NotebookLM.
- **Download/share** — public sharing or local download of goal reports; PDF/Word/Markdown/LaTeX; JSON/CSV data export; BibTeX/RIS/EndNote citations; print view.
- **Follow-up agent** — natural-language chat to continue: "explore this direction further," "compare with alternative," "refine with new constraints," "validate with literature," "generate experimental protocol." Tracks iteration history and branching exploration paths.

### How weak/non-viable ideas are handled
Not immediate rejection — an **iterative critique-and-refine cycle**:
- Reflection performs deep verification + causal analysis; classifies hypotheses as *already explained / other explanations more likely / missing piece / neutral / disproved*.
- Tournament filtering: lower-ranked hypotheses get fewer resources (single-turn vs multi-turn); Proximity clusters for de-dup; consistent losers get lower Elo and are deprioritized.
- Evolution tries to *improve* rather than discard (combine top performers, fill reasoning gaps).
- Expert-in-the-loop + wet-lab validation provide ground truth.

---

## 3. Information architecture

Hub-and-spoke: a central workspace hub connecting to functional modules, all over a conversational interface implementing Generate → Debate → Evolve.

```text
Platform Hub (Home)
├── Onboarding & Welcome
├── Research Workspace
│   ├── Goal Creation Flow
│   ├── Interview/Refinement
│   ├── Run Configuration
│   ├── Active Run Monitoring
│   └── Results & Reports
│       ├── Ideas Report
│       ├── Knowledge Base
│       ├── Summary Report
│       └── Detailed Proposals
├── Follow-up Agent Interactions
├── Project Management (History/Archive, Saved Runs, Drafts)
├── Knowledge Base
├── Settings & Preferences
└── Help & Documentation
```

**Data-flow layers:** Input (NL goals, feedback, uploads) → Processing (the multi-agent system) → Output (reports, hypotheses, knowledge bases, ranked ideas) → Storage (context memory, run history, preferences, knowledge graph).

### Screen inventory (condensed)
Home/Hub (quick-start CTA, active-runs panel, recent projects, templates gallery, activity feed); Onboarding (welcome, capability tour, domain selection, integration setup, notifications); Goal Creation; Interview/Refinement (chat + context panel + structured form + suggestion chips + file upload); Run Configuration; Active Run Monitoring; Report pages (Ideas, Knowledge Base, Summary, Detailed Proposal); Idea Detail View (statement, reasoning chain, evidence base, novelty assessment, testability analysis, evolution history, user notes); Knowledge Base Views (graph, semantic search, document viewer, citation context, export, follow-up queries); Follow-up Agent Interaction; Sharing/Export; Settings; Project/History Management.

### Navigation model
- **Top bar** — logo + Home + New Research Goal (primary CTA); global search; notifications, help, profile.
- **Collapsible sidebar** — Dashboard, Research Workspace, Knowledge Base, History, Collaboration, Settings (icons-only collapse; 1–9 shortcuts; contextual highlighting).
- **Breadcrumbs** — `Home > Workspace > [Project] > [Run] > [View]`.
- **In-view tabs** — Run view: Overview / Ideas / Knowledge Base / Tournament / Settings.
- **Contextual actions** — FAB per context; right-click menus (Compare/Export/Follow-up on ideas; Cite/Save/View on papers).
- **Drawers** — right (agent activity, citation details, feedback input); left (filters, report outline).

---

## 4. The control-console design pattern (transparent + steerable)

The UX must reject the **"Opaque Autopilot"** anti-pattern (complex work behind a generic spinner) *and* avoid dumping raw scrolling logs. The control console balances visibility and usability:

- **Interactive scoping interview** (Intake agent) — clarifies boundaries, isolates variables, flags data sources, configures domain-profile weights.
- **Visual run timeline** — milestones (Goal Scoping → Retrieval Grounding → Generation → Evaluation → Debating → Mutation → Report Synthesis) with completion %, elapsed/remaining time.
- **Active agent panel** — which agent, current sub-task, tools/DBs being accessed.
- **Running metrics console** — token usage, financial spend (e.g. *"$42.50 of $100.00 ceiling"*), indexed-document count; hard limits halt on cost/time breach.
- **Interactive handoff center** — surfaces alerts (safety warnings, low-confidence evaluations) with action controls.
- **Follow-up console** — post-run: inspect reports, browse clustered ideas, review verified Knowledge Base, query the final proposal in chat.

### Execution-state → UI mapping
Each pipeline phase exposes specific panels and **user override actions**:

| Phase | Active agents | Intermediate data | User overrides |
|---|---|---|---|
| **Scoping** | Intake, Supervisor | scoped profile, parameter payload | submit params, update domain weights, skip interview |
| **Grounding** | Literature, Safety | query sets, doc profiles, safety pass | pause retrieval, inject custom PDFs, refine terms |
| **Generating** | Generation, Proximity, Supervisor | candidate hypotheses, semantic coords | adjust diversity sliders, modify clustering, insert manual hypotheses |
| **Evaluating** | Reflection, Safety | multi-axis scores, critique reports | interrupt, modify criteria weights, flag low-confidence |
| **Debating** | Ranking, Supervisor | matchup transcripts, Elo updates, brackets | override verdicts, pause tournament, inspect transcripts |
| **Evolving** | Evolution, Supervisor | mutated hypotheses, parent-child lineage | select mutation operators, manually cross-breed |
| **Paused** | Supervisor (dormant) | checkpoint, state delta | resume, rollback to node, cancel |
| **Synthesis** | Report Synthesis, Citation Verification | draft report, claim-to-source map | reject draft, adjust formatting, trigger deep citation check |
| **Complete** | none | final proposal, clickable refs | export, follow-up query, refinement run |
| **Failed** | Supervisor | trace reports, error logs | retry node, rollback to checkpoint, export debug log |

---

## 5. Visual design system (Material 3 Expressive)

To feel like a first-party Google product, the frontend adheres to **Material Design 3 (M3) Expressive** — soft curves, structured surfaces, dynamic color roles, organic (spring-physics) motion. The reference layout is a **side-by-side split**: left = setup/controls/logs; right = interactive canvas (tournament bracket, proximity graph, final proposal) — mirroring the Gemini Canvas paradigm.

### Typography (license-safe substitutes)
Google Sans / Product Sans must **not** be packaged. Use open-source geometric substitutes:

```css
:root {
  --font-family-header: 'Spline Sans', ui-sans-serif, system-ui, sans-serif;   /* high-density headers */
  --font-family-body:   'DM Sans', ui-sans-serif, system-ui, sans-serif;       /* geometric body copy */
  --font-family-mono:   'JetBrains Mono', ui-monospace, monospace;             /* logs / structured data */
}
```

### Color tokens (M3 tonal roles, WCAG-AA enforced)
```css
@theme {
  --color-primary: #0b57d0;              --color-on-primary: #ffffff;
  --color-primary-container: #d3e3fd;    --color-on-primary-container: #041e49;
  --color-secondary: #00639b;            --color-on-secondary: #ffffff;
  --color-secondary-container: #c2e7ff;  --color-on-secondary-container: #001d35;
  --color-tertiary: #b8422e;             --color-on-tertiary: #ffffff;   /* safety alerts, debate highlights */
  --color-tertiary-container: #ffdad5;   --color-on-tertiary-container: #410002;
  --color-surface: #f8f9fa;              --color-surface-container: #ffffff;
  --color-on-surface: #1f1f1f;           --color-on-surface-variant: #444746;
  --color-outline: #747775;
  --radius-xs: 4px; --radius-sm: 8px; --radius-md: 12px; --radius-lg: 16px; --radius-xl: 24px; --radius-full: 9999px;
}
```

### Motion (spring physics, not static easing)
```css
.m3-transition-spatial {  /* stiffness 150, damping 0.8 */
  transition: transform, left, top, width, height, border-radius 350ms cubic-bezier(0.175,0.885,0.32,1.1);
}
.m3-transition-effects {  /* stiffness 220, damping 1.0 — no overshoot for color/opacity */
  transition: background-color, color, opacity 250ms cubic-bezier(0.2,0,0,1);
}
```

### Component conventions
Buttons (`--radius-full`, 40px, primary bg, hover 35% overlay + ripple); Hypothesis cards (`--radius-lg`, surface-container, outline border, hover elevation, selected = primary-container); Navigation rail (72px, spring-expander pill on select); Progress trackers (tertiary-highlighted ring/linear with shimmer sweep); Scoping modals (`--radius-xl`, upward decel spring in / downward accel out); Log tables (borderless, low-contrast separators); Error states (tertiary-container banner sliding from top, pinned until dismissed); Empty states (subdued on-surface-variant typography).

### Frontend implementation note
Open-source reference stack: **React + Vite + Tailwind + CopilotKit (AG-UI)**. Live components include `HypothesisCard`, `EloLeaderboard`, `DebateTimeline`, `CitationVerifiedBadge`. The AG-UI protocol streams **~17 typed event types** over SSE (primary) + WebSocket (dashboard): lifecycle (`RUN_STARTED`/`RUN_FINISHED`), text deltas (`TEXT_MESSAGE_CONTENT`), tool calls (`TOOL_CALL_START`/`TOOL_CALL_END`), state sync (`STATE_DELTA`), and a `THINKING` channel. `STATE_DELTA` updates the leaderboard reactively; hypothesis cards should appear within ~2s of DB insert. *(See file `03` for the full stack and the API/event contract.)*

### Non-functional UX targets
Initial load < 3s; time-to-interactive < 5s; real-time run updates (WebSocket/SSE); search < 500ms; large reports use progressive loading/virtualization. Accessibility: full keyboard nav, ARIA/semantic HTML, WCAG-AA contrast, `prefers-reduced-motion`, 200% zoom without horizontal scroll. Responsive: desktop primary (sidebar + main + optional right panel); tablet (collapsible sidebar, single column, tabs); mobile limited (bottom nav, stacked cards — complex workflows need desktop).

---

## 6. MVP scope and roadmap

### Users & use cases
**Target users:** academic/industry researchers (life/materials scientists, R&D teams) and lab leaders needing to accelerate hypothesis generation + literature review. Personas: time-poor bench scientists with domain depth; cross-domain consultants; research managers setting broad goals.

**Core use cases:** generate novel testable hypotheses grounded in literature; critique & refine ("tournament of ideas"); evidence gathering with citations (PubMed, arXiv, ChEMBL, UniProt); collaborative exploration (seed ideas/feedback); reporting (ranked hypotheses + next steps).

**Success metrics:** hypothesis novelty & correctness (expert-rated), number of validated leads, user satisfaction, reduction in research-cycle time, internal Elo-rating trends.

### Baseline (MVP) vs Extensions

| Component | Baseline (MVP) | Extensions (optional) |
|---|---|---|
| Agents | Generation, Reflection, Ranking, Evolution, Proximity, Meta-review | Domain-specific planning/creativity agents |
| Retrieval | Web search, PubMed, arXiv, ChEMBL, UniProt | AlphaFold, proprietary DBs |
| Memory | Stateless per-session + fetch caching; limited long-term | Full stateful project memory |
| UI | Web app: query input, hypothesis list, evidence links, feedback | Interactive viz (knowledge graphs, idea maps), collaboration |
| Output | Ranked hypotheses + citations + summary | JSON/PDF export, API, lab-tool integration |
| Evaluation | Elo auto-rank + manual expert panels (GPQA-style) | Full user study, continuous learning, benchmark suite |
| Safety | Filters for false/unsafe claims, disclaimers, usage monitoring | Advanced fact-checking, misuse detector, offline vetting |
| Scale | Available LLMs, small cluster | Larger/multi-LLM, optional on-prem |

### Roadmap (illustrative timeline)
```text
Phase 1 Planning:        Requirements Design (M1: sign-off)
Phase 2 Core Dev:        Infra & Data → Agent Impl (MVP) → UI (MVP) → Integration & Testing
Phase 3 Eval & Release:  Safety Review → Beta + User Trials → Official Launch (M2)
```

### Prioritized backlog (effort estimates)
Core Architecture & Planning (High, 4–6 wk); Retrieval & Data Layer (High, 8–10 wk); Agent Development MVP set (High, 10–12 wk); Supervisor & Orchestration (High, 6–8 wk); UI MVP (Medium, 6–8 wk); Evaluation Suite (Medium, 4–6 wk); Safety & Guardrails (Medium, 4–6 wk); Extension tools / advanced UI (Low, 6–8 wk each); Buffer (Medium, 4–6 wk). ~70% of effort is core. Assumes 5–8 engineers over 9–12 months; a narrower scope (PubMed-only, text-only) is feasible in 6–8 months.

### Open trade-offs
Model choice (Gemini/Claude vs cheaper/open; design model-agnostic); compute infra (cloud vs on-prem); team/budget; domain scope (life sciences first, like the original); latency vs thoroughness (fast mode = fewer cycles, deep mode = full debate). Document each so stakeholders can adjust.
