# Project documentation

| Guide | Contents |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | App, engine and MCP boundaries |
| [Engine architecture](../engine/docs/ARCHITECTURE.md) | Scientific stages and execution |
| [Local setup](RUNNING-LOCALLY.md) | Toolchain, services and worktrees |
| [CI](CI.md) | Hermetic gates and local equivalents |
| [Deployment](DEPLOYMENT.md) | Hosting, networking and configuration |
| [Operations](OPERATIONS.md) | Persistence, provider and scientific safeguards |
| [Monitoring](MONITORING.md) | Uptime checks and error tracking to set up |
| [Launch](LAUNCH.md) | Release validation, backups and security settings |
| [Dependencies](../requirements/README.md) | Hash-pinned runtime locks and audits |
| [Contributor guidance](../AGENTS.md) | Repository rules and operating invariants |
| [Parallel campaigns](CAMPAIGNS.md) | Schedule, ownership and merge rules for the three campaigns below |
| [Production cuts](PROD-CUTS.md) | Agreed feature removals, next after the test campaign |
| [Production shrink](PROD-SHRINK.md) | Behavior-preserving size reduction, folder by folder after the cuts |
| [Optimization](OPTIMIZATION.md) | Performance, efficiency and launch readiness |
| [Re-architecture](REARCHITECTURE.md) | Target structure, phases and rules for the next campaign |
| [Re-architecture survey](rearchitecture/survey.md) | Phase 0 measurements: sizes, import graph, hot spots, break points |
| [Glossary](GLOSSARY.md) | Domain terms used in module and type names |
| [Architecture decisions](adr/) | ADR-001 module map, ADR-002 layering, ADR-004 LLM gateway, ADR-005 tracing |

Retired audits, guides, incident records and screenshots remain in
[immutable history at 33ec8984](https://github.com/guy915/Co-Scientist/tree/33ec8984c6f9292a6653cc6a661d32210f55c688/docs).
Runtime prompt templates remain beside the engine source.
