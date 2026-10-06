# Security policy

## Reporting a vulnerability

Report vulnerabilities privately. Do not open a public issue, pull request or
discussion.

1. Open the repository's **Security** tab.
2. Select **Report a vulnerability**, or go to
   [the advisory form](https://github.com/guy915/Co-Scientist/security/advisories/new).
3. Describe the problem, the affected component, and the steps to reproduce it.

Do not include real credentials, researcher data, or the contents of a
production database. A minimal proof of concept against your own local
checkout is enough.

We aim to acknowledge a report within 7 days. After that we will keep you
informed while we confirm, fix and disclose the issue, and we will credit you
in the advisory if you want to be named.

## Scope

In scope:

- The API (`app/`), including authentication, session and ownership checks, and
  report sharing.
- The reference MCP server (`engine/mcp_server/`), including its URL guards.
- The sandbox that confines model-written programs, and the rule that
  execution tools are absent when confinement is unavailable.
- Handling of bring-your-own-key (BYOK) provider credentials.
- The hosted site at https://ai-co-scientist.com/ and its API.

Out of scope:

- Vulnerabilities in third-party model providers, scientific data sources or
  other upstream services. Report those to the provider.
- Findings that require an already compromised machine, browser or account.
- Vendored code under `vendor/` that is unmodified upstream; report it
  upstream (see [NOTICE](NOTICE)).
- Denial of service through volume alone, and automated scanner output without
  a demonstrated impact.
- Local development mode (`AUTH_MODE` compatibility), which uses
  caller-selected IDs by design and is not meant to be exposed.

## Supported versions

Only the latest commit on `main` and the current hosted deployment receive
security fixes. There are no maintained release branches.

## Safe harbor

We will not pursue or support legal action against good-faith security
research that follows this policy. Act in good faith: test against your own
local checkout or your own hosted account, do not access or change other
users' data, do not degrade the service for others, and give us reasonable
time to fix an issue before you disclose it.
