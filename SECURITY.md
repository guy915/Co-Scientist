# Security

Report a suspected vulnerability privately through the repository's
[security advisory form](https://github.com/guy915/Co-Scientist/security/advisories/new).
If private reporting is unavailable, contact the maintainer through the
[GitHub profile](https://github.com/guy915) before publishing exploit details.
Include affected versions, reproduction steps, impact, and a minimal example.
Remove provider keys, access codes, researcher data, and session tokens.

Security fixes target the current `main` branch. Tagged older versions have
no separate maintenance commitment.

## Deployment boundaries

- Use `AUTH_MODE=required` on an internet-facing API. Compatibility mode
  accepts caller-selected `X-Client-ID` values for local development; those
  values do not prove identity. Configure a random signing secret and unique,
  high-entropy researcher access codes. Invalid auth modes and required auth
  without a secret fail during configuration loading.
- Invite exchanges have a per-IP attempt limit (`AUTH_EXCHANGE_PER_MINUTE`,
  default 20). Run one API process. Configure trusted proxy forwarding at
  the server boundary; never trust arbitrary client-supplied forwarded
  addresses. A distributed deployment needs a shared limiter.
- Keep the MCP service private and set matching `COSCIENTIST_MCP_SHARED_SECRET`
  values on the API and MCP service. Its status endpoint is public within
  that private network; other endpoints require the configured secret.
- Keep `.env` files, SQLite stores and their sidecars, credentials, reports,
  and caches outside Git and Docker build contexts. `.env.example` files
  must contain placeholders only. A clean working tree does not establish
  that Git history is free of secrets.
- Model-generated programs and retrieved pages are untrusted. Preserve the
  engine's filesystem confinement and network policy, MCP URL guards, tool
  budgets, and scientific safety gates. Execution tools must remain unavailable
  when confinement cannot be established.
- Protect BYOK credentials with the separate `BYOK_ENCRYPTION_KEY`. Do not
  reuse the auth signing secret. Rotating this key requires a deliberate
  migration or removal of the affected encrypted credentials.

Authorization, ownership isolation, credential disclosure, SSRF, sandbox
escapes, and dependency integrity are relevant security issues. Scientific
claim quality and wet-lab validity require separate evaluations; a passing
security test does not establish either.

See [deployment](docs/DEPLOYMENT.md) and [launch readiness](docs/LAUNCH.md)
for the production configuration and release checks.

Run `make audit-deps` for current dependency advisories. The dated
[dependency review](docs/DEPENDENCY-SECURITY.md) records patched versions and
the reachability assessment for remaining detector findings.
