# Project documentation

| Guide | Contents |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | Layers, package map, persistence and request path |
| [Engine architecture](../engine/docs/ARCHITECTURE.md) | Agents, durable workflow and orchestration |
| [Glossary](GLOSSARY.md) | Domain terms used in module and type names |
| [Architecture decisions](adr/) | Module map, layering, durable runtime, LLM gateway, tracing |
| [Local setup](RUNNING-LOCALLY.md) | Toolchain, services and worktrees |
| [CI](CI.md) | Hermetic gates and local equivalents |
| [Deployment](DEPLOYMENT.md) | Hosting, networking and configuration |
| [Operations](OPERATIONS.md) | Persistence, provider and scientific safeguards |
| [Monitoring](MONITORING.md) | Uptime checks, error tracking and tracing |
| [Launch](LAUNCH.md) | Release validation, backups and repository settings |
| [Evaluations](../evaluations/README.md) | Offline harness and live benchmark |
| [Dependencies](../requirements/README.md) | Hash-pinned runtime locks and audits |
| [Engine package](../engine/README.md) | Engine install and development |
| [MCP server](../engine/mcp_server/README.md) | Reference literature and database tools |
| [Frontend](../app/frontend/README.md) | Workbench commands and source layout |
| [Contributor guidance](../AGENTS.md) | Repository rules and operating invariants |

Runtime prompt templates live beside the engine source in
`engine/src/co_scientist/science/prompts/templates/`.
