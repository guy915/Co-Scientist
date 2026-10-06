# Monitoring

Production has no error tracking or external uptime check yet. Railway's
healthcheck runs only while a deploy goes live; after that nothing polls the
service. This guide lists what to create and where the code hooks in.

## Uptime

Use a free external monitor (UptimeRobot, Better Stack or similar) with a
five-minute interval and email alerts.

| Monitor | URL | Alert when |
|---|---|---|
| API up | `https://api.ai-co-scientist.com/health` | status is not 200 |
| API healthy | same URL, keyword check | `"status":"healthy"` is absent |
| Site up | `https://ai-co-scientist.com/` | status is not 200 |

`/health` returns 503 only when the store is unreachable. A stuck run, a
terminally failed task or low disk report `"status":"degraded"` with 200, so
the keyword monitor is what catches them. The public response hides check
detail, so it is safe to poll. Do not monitor the MCP service: it is private
to Railway's network.

## Error tracking

Use Sentry's free tier (or self-hosted GlitchTip, which speaks the same
protocol) with one project for the API and one for the frontend.

| Where | Variable | Value |
|---|---|---|
| Railway, api | `SENTRY_DSN` | the API project's DSN |
| Railway, api | `SENTRY_ENVIRONMENT` | `production` |
| Vercel, production | `VITE_SENTRY_DSN` | the frontend project's DSN |
| Vercel, build (optional) | `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT` | source-map upload for readable stack traces |

Both SDKs stay off while their DSN is unset, so local runs, CI and forks
send nothing. Researcher data must not leave through error reports: the
API sends no request bodies, no personal data and no performance traces,
and it scrubs provider keys with the same filter as the logs.

## Status

- Uptime monitors: owner action (accounts and alert contacts).
- Error tracking: the API and frontend hooks land after the production cuts
  free `app/requirements-app.txt` and the frontend entry point; until then
  the variables above have no effect.
