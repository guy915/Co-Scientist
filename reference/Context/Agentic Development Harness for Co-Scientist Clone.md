# Engineering an Agentic Software Development Harness for the DeepMind Co-Scientist Clone

## Architectural Mapping of the Co-Scientist Agentic Development Harness

Constructing a 1:1 clone of Google DeepMind’s AI Co-Scientist requires a highly specialized, local development environment. Operating this project through an agentic software-production harness like Claude Code allows autonomous agents to assume the burden of repository management, file operations, test execution, and deployment. Rather than treating the agent as a simple chatbot, the engineering pipeline integrates the agent directly into local filesystems, databases, browser automation scripts, and continuous integration engines.

The primary target is the automated implementation of Google’s Hypothesis Generation workflow, which encompasses research-goal setup, interview-style scoping, Standard/Advanced execution runs, generated reports, ranked ideas, a secure Knowledge Base, Run Specifications, and subsequent follow-up interactions. The system architecture coordinates a web UI, backend API, long-running job queue, scientific retrieval layer, hypothesis store, evidence/citation verification system, tournament/ranking engine, report generator, and a fidelity evaluation harness.

To optimize the development of this multi-agent structure, the engineering team configures the workspace as an active coordination framework. The architectural division between the different extensibility points dictates how the coding agent implements each component of the target application:

|**Co-Scientist Target Module**|**Functional Dev Role**|**Dev Engine Extension**|**Primary Dev Tooling / Command**|**Verification Strategy**|
|---|---|---|---|---|
|**Scoping UI & Interview Module**|Frontend / Web UI|Playwright MCP & Claude Agent SDK|`browser_navigate`, `browser_click`|Verify design-system compliance and user entry paths.|
|**Literature Retrieval Layer**|Scientific retrieval & vector search|Supabase & Postgres MCP|`execute_sql`, `list_extensions`|Setup `pgvector` indexing and index scientific metadata.|
|**Hypothesis Gen & critique**|Multimodal LLM orchestrator|Reusable Skills / Custom subagents|`.claude/skills/generate-hypothesis/`|Execute `/batch` for parallel generation script structures.|
|**Tournament Engine**|Game-theory evaluation & ranking|Custom Skills / SQLite MCP|`/loop`, `/simplify`|Evaluate tournament scoring logic for high-concurrency.|
|**Evidence/Citation System**|Verifying paper URLs & DOIs|Web Request & Git MCP|`gh-actions-mcp`, WebFetch|Test accuracy of retrieval pipelines through automated runners.|
|**Safety Layer & Job Queue**|Compliance & asynchronous runs|Deterministic Hooks|PreToolUse / PostToolUse|Prevent hallucinated commands or insecure API interactions.|

By structuring the workspace in this manner, the autonomous coding agent transitions from a passive generator of isolated code modules to an active coordinator capable of managing complex development operations.

## Model Orchestration, Planning, and Context Engineering

The execution of a long-running, autonomous development campaign requires precise control over the underlying model configuration, reasoning depth, and context footprint. The coding agent must dynamically adapt its cognitive capabilities depending on whether it is mapping out high-level architectures or writing boilerplate API endpoints.

### Model Configurations and Aliases

The default orchestration engine of the development harness is configured via settings or environment variables to target specific model variants depending on the execution context. On the Anthropic API, the `opus` alias resolves to Opus 4.8, while the `sonnet` alias maps to Sonnet 4.6. For third-party cloud environments, such as AWS Bedrock, Google Vertex, or Microsoft Azure Foundry, these aliases automatically adjust to local deployment names and inference profile ARNs (for example, mapping `opus` to Opus 4.7 or Opus 4.6 depending on provider support).

A highly efficient configuration utilized for full-stack implementation is the `opusplan` hybrid model alias. This routing profile automates the cognitive balance:

```
                 
                          │
                          ▼
                 
                    /           \
         (Plan Mode)             (Execution Mode)
             /                       \
            ▼                         ▼
      [Opus 4.8 / 4.7]         
   (Architectural Design)     (Code Implementation)
```

During architectural planning phases, the harness routes prompts to the highly capable Opus model to handle structural design, safety guardrails, and dependency routing. Once the plan is finalized, the harness seamlessly transitions execution to Sonnet to perform high-speed, token-efficient code generation across files.

### Effort Levels and Ultracode Workflows

The developer manages the agent's computational intensity using the `/effort` slider, adjusting settings between low, medium, high, xhigh, and max. While standard debugging tasks operate efficiently at medium or high, complex agent coordination tasks (such as resolving competitive game-theory states in the Co-Scientist tournament logic) are executed with `xhigh` or `max` effort.

For critical modules, the developer enables `ultracode` mode. This setting instructs the system to combine maximum reasoning effort with dynamic background workflows, allowing a lead agent to coordinate multiple subagents to parallelize testing and verification.

### Context Engineering and Session Compaction

To prevent token exhaustion and maintain system focus, the harness utilizes a series of context-management commands. The `/plan` mode is activated proactively before starting any major feature branch, switching the agent into a dedicated planning state to compile specifications before editing files.

To ask ephemeral questions without bloating the conversational history, developers invoke `/btw`, keeping the main context clean. When conversations grow long, `/context` visualizes the active token distribution as a grid.

The developer then utilizes `/compact` to summarize the history. The total active context $T_{\text{context}}$ during a development session can be mathematically modeled as:

$$T_{\text{context}} = T_{\text{history}} + \sum_{i=1}^{n} S_i + T_{\text{system}} + T_{\text{mcp}}$$

where $T_{\text{history}}$ represents conversational history, $S_i$ is the active skill footprint, $T_{\text{system}}$ is the system instructions (such as `CLAUDE.md`), and $T_{\text{mcp}}$ represents the registered MCP tool definitions.

When compaction triggers, the CLI re-attaches up to the first 5,000 tokens of each recently invoked skill, up to a maximum total skill budget of 25,000 tokens, to optimize model focus without losing necessary rules. The `/clear` command is used between distinct coding cycles to reset the session context entirely while preserving project memory within the local `CLAUDE.md` and automated memory files.

## Full-Stack Implementation: Frontend, Backend, and Database Mechanics

Building a complex, data-intensive system such as the Co-Scientist clone requires a highly integrated set of external tools. Rather than manually writing database schemas, styling components, or testing API endpoints, the developer connects Claude Code to a specialized ecosystem of Model Context Protocol (MCP) servers.

### Database Schema Orchestration

The database layer, which serves as the core storage for scientific hypotheses, evidence chains, and tournament results, is developed using the Supabase and PostgreSQL MCP servers. The developer utilizes the `execute_sql` tool to generate database structures, check constraints, and set up relational schemas.

To protect the development workspace from accidental data loss or mutation during test cycles, the connection tab is configured in read-only mode by passing the `read_only=true` query parameter. Mutating commands, such as `apply_migration` or `deploy_edge_function`, are strictly disabled in this mode, preventing unauthorized alterations during automated code-analysis routines.

### Frontend and Web UI Automation

Implementing the Scoping UI and dashboard is streamlined using the Playwright MCP server. Operating on the browser's accessibility tree rather than visual screenshots or brute-force DOM parsing, the agent navigates using `browser_navigate`, inputs parameters into the scoping interview form using `browser_type`, and clicks buttons using `browser_click`.

To ensure session persistence across development runs, the system is configured to target a user data directory:

JSON

```
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--user-data-dir", "./.playwright-profiles/dev-user"]
    }
  }
}
```

This configuration preserves cookies and local storage, bypassing repetitive authentication screens during iterative browser tests. For complex UI interactions, the agent utilizes `browser_run_code_unsafe` to execute raw JavaScript scripts directly in the page context.

Because this command operates with high execution privileges, it is treated as a remote code execution equivalent and restricted to trusted local clients.

|**MCP Server Name**|**Target Task**|**Specific Tools Exposed**|**Integration Outcome**|
|---|---|---|---|
|**PostgreSQL**|Analyzing relational schemas and tables|`inspect_schema`, `execute_query`|Verifies structural consistency of the tournament score tracking tables.|
|**Supabase**|Project-level scaffolding & migrations|`apply_migration`, `deploy_edge_function`|Automatically handles database migrations and edge server deployments.|
|**Playwright**|Scoping UI accessibility validation|`browser_snapshot`, `browser_click`, `browser_type`|Executes continuous integration testing of the scoping forms.|
|**Brave Search**|Context-grounding literature collection|`brave_search`|Provides real-time search queries to seed the initial Knowledge Base.|
|**Context7**|Pulling third-party API documentation|`fetch_docs`|Supplies up-to-date documentation on scientific publishing endpoints.|
|**Linear**|Coordinating issue tracking and tickets|`list_issues`, `update_issue_status`|Syncs the coding agent's progress with project management tickets.|

## Testing, Debugging, and Quality Verification Protocols

Ensuring high fidelity and reliability in the Co-Scientist clone requires continuous, automated verification. The agentic development harness incorporates specialized tools designed to run, test, and simplify code without requiring manual terminal supervision.

### Automated Application Driving and Schema Verification

The developer relies on the built-in commands `/run` and `/verify` to validate code changes. When a code block is modified (for example, refactoring the literature retrieval module), the agent triggers `/verify` to compile the application, execute standard test suites, and confirm the platform's baseline integrity.

If the repository utilizes a custom or non-standard build configuration, `/run-skill-generator` is executed first to teach `/run` and `/verify` the exact commands necessary to build and launch the project. This removes the need for the project director to manually provide compilation flags or execution arguments.

To optimize codebase quality and eliminate logical redundancies, the developer chains the `/simplify` skill immediately after any significant code generation task. This skill executes a refinement pass over the modified code, identifying subtle redundancies, unused imports, or non-optimal structures that are often missed during high-speed initial generation phases.

If runtime errors or compile failures occur, `/doctor` and `/debug` are invoked to run diagnostics on the installation health and local environment, presenting instant fixes for missing packages or misconfigured environment paths.

```
                     [Code Modification]
                             │
                             ▼
                    [Execute /verify] ─── (Failure) ───> [Execute /debug]
                             │                                     │
                         (Success)                              (Fixes)
                             │                                     │
                             ▼                                     ▼
                    [Execute /simplify] ──────────────────> [Apply Changes]
```

### CI/CD Integration and Pipeline Monitoring

For enterprise-scale tracking, the development harness incorporates the `gh-actions-mcp` server. This server connects the local coding session to the repository's GitHub Actions pipeline, giving the agent direct visibility into remote build states.

The agent utilizes the `get_actions_status` tool to check pipeline health and the `analyze_timing` tool to evaluate step durations across recent runs. This analytical verification is critical for spot-checking performance regressions in the Co-Scientist simulation queue.

If a remote build is blocked or needs verification, the agent triggers a manual workflow run using the `trigger_workflow` tool, passing required runtime inputs (such as staging environment targets) to the GitHub API:

JSON

```
{
  "name": "trigger_workflow",
  "arguments": {
    "workflow_id": "ci.yml",
    "ref": "main",
    "inputs": {
      "test_suite": "tournament-ranking-engine",
      "debug_logging": "true"
    }
  }
}
```

This direct pipeline control allows the coding agent to handle the entire lifecycle of a code change—from writing the files and creating the pull request to monitoring the CI pipeline and resolving any remote build failures autonomously.

## Reusable Knowledge Packaging and Execution Hooks

Standardizing development workflows across a distributed engineering team requires translating abstract coding guidelines into repeatable, automated operations. The coding harness implements this standardization using a combination of customized Agent Skills and deterministic Lifecycle Hooks.

### Creating Customized Agent Skills

While the global `CLAUDE.md` is reserved for static system context (such as preferred libraries, styling patterns, and core file maps), complex multi-step procedures are packaged into reusable Skills. Unlike `CLAUDE.md`, which is loaded into context at the beginning of every turn, a skill's full text is loaded only when triggered. This progressive disclosure saves significant context tokens during long-running sessions.

Skills are structured as standalone directories inside the repository, housing the main instruction file along with supporting schemas or testing scripts. For example, the tournament verification routine is declared under `.claude/skills/verify-citations/SKILL.md` :

name: verify-citations

description: Parses the generated Co-Scientist research proposal and cross-references citation targets with open APIs

disable-model-invocation: true

user-invocable: true

allowed-tools:

- Bash(python3 scripts/verify_urls.py *)
    

# Citations Verification Protocol

1. Read the raw text of the generated research proposal.
    
2. Locate all markdown citations of the format `[source_id]`.
    
3. Extract corresponding URLs from the evidence store.
    
4. Execute the validation script `python3 scripts/verify_urls.py` with the extracted links as arguments.
    
5. Report any broken links or unverified scientific claims to the main console.
    

The YAML frontmatter configuration determines the accessibility of the skill :

- **disable-model-invocation**: Setting this property to `true` prevents Claude from triggering the skill autonomously based on conversational context. This is used for operations with side effects (such as deploying code, mutating databases, or sending Slack notifications) where human confirmation of timing is mandatory.
    
- **user-invocable**: Controls whether the command is visible to developers in the active `/` CLI menu.
    
- **allowed-tools**: Pre-approves specific tool executions, allowing the agent to run local verification scripts without prompting the user for confirmation. This property is supported when using the Claude Code CLI directly; it does not apply when running skills programmatically through the Claude Agent SDK, where tool permissions are configured globally.
    

### Enforcing Rules Deterministically with Hooks

While Skills provide guidance that the agent _should_ follow, Hooks enforce rules that _must_ be executed. A hook is a deterministic executable command triggered by the CLI harness at a specific point in the conversational lifecycle, running independently of the underlying LLM's state.

JSON

```
{
  "hooks": {
    "SessionStart": [
      {
        "command": "git fetch origin && git status"
      }
    ],
    "UserPromptSubmit": [
      {
        "command": "python3 scripts/scan_prompt_secrets.py"
      }
    ],
    "PreToolUse":
      }
    ],
    "PostToolUse":
  }
}
```

This lifecycle layout ensures that:

- **SessionStart**: Automatically updates local repository states and informs the agent of the branch alignment before starting work.
    
- **UserPromptSubmit**: Scans developer inputs for hardcoded keys or API credentials before transmitting data to external LLM servers.
    
- **PreToolUse**: Acts as a strict system-level interceptor. If the agent attempts to run a destructive shell command (e.g., `rm -rf /` or unauthorized network exfiltration), the hook returns a non-zero exit code, blocking the tool call and sending a refusal back to the model as the tool outcome.
    
- **PostToolUse**: Automatically runs formatting or type-checking scripts on any modified or written files. This maintains styling and linting compliance across all generated frontend and backend files without requiring developer oversight.
    

## Multi-Agent Parallel Coordination and Task Synchronization

Developing a complex multi-agent ecosystem such as the Co-Scientist clone requires establishing parallel software development workflows. Developers leverage two primary models to coordinate tasks across concurrent streams: hierarchical delegation and flat peer-collaboration.

### Hierarchical Delegation vs. Flat Collaboration

In a hierarchical structure, a lead supervisor agent maintains overall task authority, spawning specialized subagents (such as literature retrieval or ranking agents) to execute targeted subtasks in isolated contexts. These subagents are given limited tools and focused context windows to optimize execution speed and prevent context bloat in the main session. The outputs from these subagents are returned directly to the supervisor, who synthesizes the final codebase modifications.

In flat peer-collaboration (Agent Teams), multiple agents work as peers, coordinating their tasks through a shared task list rather than a top-down manager.

The task board is represented as a structured markdown file (`TASKS.md`) containing distinct implementation steps:

# Co-Scientist Clone Implementation Board

- [x] Refactor scientific citation verification rules (Claimed by Agent_1)
    
- [/] Integrate pgvector indexing in database layer (Claimed by Agent_2)
    
- [ ] Implement scoping interview socket connections (Pending)
    
- [ ] Deploy safety classification checks (Blocked by socket connections)
    

When an agent finishes its active work, it updates its task status to complete, scans the shared document, finds an unassigned pending task, updates the status marker with its unique ID to lock the task, and begins execution. This flat collaboration pattern offers:

- **Persistence**: If an individual agent process crashes or is interrupted, the state of the active task board remains intact on disk, allowing other agents to resume the work seamlessly.
    
- **Transparency**: Human developers can read the `TASKS.md` file at any point to track precisely which agent is working on which module, observing the progress of the entire team from a single file.
    
- **Granular Dependency Mapping**: Hard dependencies (e.g., waiting for socket connections before deploying safety checks) are represented directly in the markdown file, ensuring agents do not execute tasks out of sequence.
    

### Desktop and Mobile Task Management

To coordinate these parallel activities across team workspaces, developers can leverage AgentsRoom. AgentsRoom serves as a local command center that manages up to 14 role-based agent templates (such as DevOps, QA, Backend, and Frontend), synchronizing personal prompts and terminal activities.

Importantly, workspace configurations stay local, and personal prompts are synchronized across developers' authorized desktop and mobile devices using end-to-end encryption via X25519 key exchange and XSalsa20-Poly1305 encryption. This architecture enables developers to manage active coding sessions, receive build alerts on mobile, and review generated code on-call without exposing codebases to third-party cloud infrastructure.

### Isolating Sessions with Worktrees

When running parallel sessions on a single machine, there is a risk of agents overwriting the same files or stomping on each other's git commits. To prevent this, the harness utilizes git worktree isolation:

JSON

```
{
  "isolation": "worktree"
}
```

When a parallel agent session is initialized, Claude Code automatically creates a separate git worktree directory for that run. The agent executes its assignments, runs tests, and commits its modifications within this isolated checkout. Once the task is completed and the changes are merged back to the primary branch, the harness automatically tear down the temporary worktree, ensuring conflict-free parallel software development.

## Security Governance, Sandbox Isolation, and Risk Containment

Deploying autonomous coding agents with access to local filesystems and remote repositories introduces security risks, particularly when processing untrusted scientific texts or web resources. Prompt injection vulnerabilities can allow external inputs to hijack the agent's instructions, forcing it to execute destructive commands or exfiltrate sensitive credentials.

### The Read Tool Environment Bypass Vulnerability

A critical security vulnerability identified by Microsoft Threat Intelligence in pre-2.1.128 versions of Claude Code highlighted the risk of partial isolation models. While shell command executions via the `Bash` tool were restricted under secure Bubblewrap namespaces on Linux, file read operations using the native `Read` tool ran as direct, in-process calls, bypassing the sandbox perimeter.

Under a prompt injection exploit (e.g., processing a paper with an embedded malicious payload), the model could be hijacked to read the runner's environment directory:

```

            │ (Contains malicious injection payload)
            ▼

            │
            ▼
    ─── (Bypasses Sandbox) ───> Reads /proc/self/environ 
            │                                             │
            ▼                                             ▼
[Exfiltration Command] <─────────────────────────── Contains API Keys 
```

The model would then exfiltrate these active credentials using an unblocked network destination via the `WebFetch` tool or by posting a public comment using the GitHub MCP server.

This vulnerability was mitigated in version 2.1.128 by unconditionally blocking access to `/proc` and sensitive system paths. However, developers must still enforce strict, defense-in-depth isolation protocols. The probability of a successful exfiltration event $P(\text{exfiltrate})$ can be modeled as:

$$P(\text{exfiltrate}) = P(\text{inject}) \cdot P(\text{bypass}) \cdot P(\text{network})$$

where $P(\text{inject})$ is the probability of a prompt injection vector, $P(\text{bypass})$ is the bypass probability of system security filters, and $P(\text{network})$ is the probability of an available exfiltration path (e.g., unblocked network domains or unmonitored write tools).

### Enterprise Security Best Practices

To safeguard the development environment and minimize the exfiltration risk, the engineering team enforces a strict security configuration:

1. **Disable Bypass Options**: Administrators set `permissions.disableBypassPermissionsMode` and `permissions.disableAutoMode` to `"disable"` in managed settings, preventing developers or hijacked models from executing tools without human-in-the-loop confirmation.
    
2. **Scrub Process Environments**: Enable `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` to strip active environment variables (such as AWS access keys, GitHub tokens, and Anthropic API keys) from subprocesses spawned by the agent.
    
3. **Containerize the Workspace**: Execute all agent sessions within isolated development containers (Devcontainers) or secure virtual machines, ensuring that even if an agent is compromised, the host filesystem is protected.
    
4. **Enforce Read-Only Database Scopes**: When connecting databases to the development harness, developers connect using a read-only Postgres user role to prevent accidental schema drops or database corruption.
    
5. **Implement Temporary Credentials**: Avoid hardcoding long-term API keys in plaintext JSON files. Configure the harness to use short-term tokens, AWS STS assumed roles, or Entra ID single sign-on mechanisms. When local configuration files require tokens, reference them via environment variable expansion (e.g., `${ANTHROPIC_API_KEY}`) to prevent committing active keys to git.
    

## Strategic Deployment and Recommendations

To establish this agentic software production harness and begin the autonomous construction of the Co-Scientist clone, the following execution plan is recommended:

### Workspace Initialization

Run the initialization command inside a fresh repository directory to set up the default workspace parameters :

Bash

```
claude /init
```

Refine the generated `CLAUDE.md` to establish development guidelines, specifying database structures (PostgreSQL / Supabase), code-style patterns, and multi-agent component interfaces.

### Setting Up Core Extensions

Install the Depwire MCP server to map codebase dependencies, the Supabase MCP server to manage relational database schemas, and the Playwright MCP server to test the scoping user interface :

Bash

```
claude mcp add depwire-cli npx depwire-cli
claude mcp add supabase-mcp npx @supabase/mcp-server
claude mcp add playwright npx @playwright/mcp@latest
```

### Developing Core Agent Modules

To develop the twelve core Co-Scientist agents, the developer invokes `/plan` mode to outline implementation specifications. This planning phase defines the functional boundaries of each module, ensuring clear architectural separation before writing code.

The coding agent then implements these agents in parallel using Git Worktree isolation to prevent file conflicts. The development sequence progresses through distinct operational stages:

```
 ──> ──>
                │                               │                            │
      (Brave Search & WebFetch)               (Supabase)                 (Playwright)
```

1. **Retrieval & Citation Verification**: The literature retrieval and citation verification agents are built using Brave Search and WebFetch MCP servers to handle document queries and DOI lookups.
    
2. **Database Scaffolding**: The database schema and tournament store are scaffolded using Supabase, executing SQL migrations with the database connection set to `read_only=true`.
    
3. **UI Integration**: The web-based scoping and interview dashboard are developed using Playwright, verifying frontend design and user paths through accessibility snapshots.
    

Throughout this pipeline, progress is tracked using the Linear MCP server, keeping task definitions in sync with active code changes.

### Pipeline Verification

Verify the application's runtime status and code quality using the built-in validation commands :

Bash

```
claude /verify
claude /simplify
```

These commands compile the application, run active test suites, and refine the code structure to remove redundancies and optimize execution speed.

### Implementing Deterministic Security Guardrails

Deploy PreToolUse and PostToolUse lifecycle hooks in `.claude/settings.json` to prevent key exposure, block unauthorized shell commands, and format code automatically on save. Run all development sessions inside isolated containers to ensure safe, autonomous, and high-fidelity code execution.