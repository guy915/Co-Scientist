# Fidelity-audit runtime evidence — 2026-07-20

This is the sanitized durable ledger for the two isolated offline runs cited as `R1-R3` in the companion fidelity diff. It records control-flow and publication behavior only. It does not establish scientific quality, external-provider behavior, or Google parity.

## Environment and launch

Repository revision: `11a310825f9fc53afb6e9cbbb443514e5db1fc84`

```bash
cd app
env \
  COSCIENTIST_DB_PATH=/tmp/cosci-fidelity-audit.PVBi1v/coscientist.db \
  COSCIENTIST_CACHE_DIR=/tmp/cosci-fidelity-audit.PVBi1v/cache \
  COSCIENTIST_FORCE_OFFLINE=1 \
  ../.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8008
```

`MCP_SERVER_URL` and `TOOLS_CONFIG` were unset. The app logged the configured default model as `deepseek/deepseek-chat`, but the authoritative `runs.llm_backend` column was `offline` for both runs and the deterministic offline router handled model calls. The nested `config_json.llm_backend` field remained `null` because no per-run backend override was supplied; it is distinct from the resolved run/backend column.

## Reproduction requests

The following bodies reproduce the exact persisted goal/setup/config inputs. A replay produces a new run ID; substitute the ID returned by each create request into its start request.

### Standard

Original run ID: `d58f0e54-cd9c-4aaa-8865-6e41f77ad343`

Client ID: `5c42a46c-5b29-4f0c-bb3d-60ac29d2019a`

```bash
curl --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' \
  -H 'X-Client-ID: 5c42a46c-5b29-4f0c-bb3d-60ac29d2019a' \
  --data '{"research_goal":"Determine how circadian timing alters macrophage resolution of sterile inflammation, with testable perturbations.","requirements":["Use mammalian models"],"attributes":["Circadian immunology"],"criteria":["Testability"],"focus":"balance","tier":"standard","enable_literature_review":false,"enable_web_search":true,"enable_paper_corpus":true}' \
  http://127.0.0.1:8008/api/runs

curl --fail-with-body --silent --show-error \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'X-Client-ID: 5c42a46c-5b29-4f0c-bb3d-60ac29d2019a' \
  --data '{}' \
  http://127.0.0.1:8008/api/runs/RETURNED_RUN_ID/start
```

Persisted resolved configuration:

```json
{
  "initial_hypotheses_count": 8,
  "max_iterations": 2,
  "evolution_max_count": 8,
  "tournament_pairs": 12,
  "evidence_count": 8,
  "max_llm_calls": 2500,
  "focus": "balance",
  "setup": {
    "goal": "Determine how circadian timing alters macrophage resolution of sterile inflammation, with testable perturbations.",
    "requirements": ["Use mammalian models"],
    "attributes": ["Circadian immunology"],
    "criteria": ["Testability"],
    "focus": "balance",
    "tier": "standard"
  },
  "enable_literature_review": false,
  "tier": "standard",
  "k_factor": 24,
  "llm_backend": null,
  "enable_web_search": true,
  "enable_paper_corpus": true
}
```

### Ultra

Original run ID: `e09f380d-6f6e-4f94-a544-f671f44bd7e7`

Client ID: `b446a2e2-0474-4838-a3bf-7418f528506b`

```bash
curl --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' \
  -H 'X-Client-ID: b446a2e2-0474-4838-a3bf-7418f528506b' \
  --data '{"research_goal":"Determine how circadian timing alters macrophage resolution of sterile inflammation, with testable perturbations.","requirements":["Use mammalian models"],"attributes":["Circadian immunology"],"criteria":["Testability"],"focus":"balance","tier":"ultra","enable_literature_review":false,"enable_web_search":true,"enable_paper_corpus":true}' \
  http://127.0.0.1:8008/api/runs

curl --fail-with-body --silent --show-error \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'X-Client-ID: b446a2e2-0474-4838-a3bf-7418f528506b' \
  --data '{}' \
  http://127.0.0.1:8008/api/runs/RETURNED_RUN_ID/start
```

Persisted resolved configuration:

```json
{
  "initial_hypotheses_count": 16,
  "max_iterations": 4,
  "evolution_max_count": 16,
  "tournament_pairs": 32,
  "evidence_count": 16,
  "max_llm_calls": 14000,
  "focus": "balance",
  "setup": {
    "goal": "Determine how circadian timing alters macrophage resolution of sterile inflammation, with testable perturbations.",
    "requirements": ["Use mammalian models"],
    "attributes": ["Circadian immunology"],
    "criteria": ["Testability"],
    "focus": "balance",
    "tier": "ultra"
  },
  "enable_literature_review": false,
  "tier": "ultra",
  "k_factor": 24,
  "llm_backend": null,
  "enable_web_search": true,
  "enable_paper_corpus": true
}
```

## Sanitized results

| Field | Standard | Ultra |
|---|---:|---:|
| Created UTC | 2026-07-20T21:00:13Z | 2026-07-20T21:06:54Z |
| Completed UTC | 2026-07-20T21:05:28Z | 2026-07-20T21:08:29Z |
| Wall seconds | 314.261 | 95.116 |
| Report execution seconds | 66.59573483467102 | 23.8693904876709 |
| Hypotheses / leaderboard entries | 6 | 10 |
| Evidence rows | 0 | 0 |
| Matches | 12 | 32 |
| Claim-gate `block` decisions | 6 | 10 |
| `insufficient` claim rows | 30 | 50 |
| High Potential entries | 5 | 5 |
| Non-Viable entries | 0 | 0 |
| Intake / final decision | allow / allow | allow / allow |
| Hypothesis state / safety state | 6 active / allow | 10 active / allow |
| Report payload SHA-256 | `a4d06dc0984f6ce9683e48051fd6b4c61634994f6da943821f7e8c9a19344614` | `064bc8ac9b6c904f2caf5f7a493e7dcf7529c0296f0914b939943b43a10f02aa` |
| Report Markdown SHA-256 | `fadee031539715aba2f39fb236f5e0050c533bc439391427236de436a5268ae6` | `64a28553fa333a21300b01c6b0f26c9841e4573eeda538b1789a79932defad42` |

The hashes are over the corresponding `sqlite3` text output including its trailing newline. The raw reports are intentionally not committed because they contain deterministic pseudo-scientific text; preserving them could invite scientific-capability credit that this audit explicitly rejects.

## Read-only reconciliation queries

The exact shell extraction used the audit database path directly:

```bash
AUDIT_DB=/tmp/cosci-fidelity-audit.PVBi1v/coscientist.db

sqlite3 -json "$AUDIT_DB" \
  "SELECT id, research_goal, profile, status, provider, config_json,
          client_id, created_at, updated_at, completed_at, error, llm_backend
   FROM runs
   WHERE id IN (
     'd58f0e54-cd9c-4aaa-8865-6e41f77ad343',
     'e09f380d-6f6e-4f94-a544-f671f44bd7e7'
   );"

sqlite3 -header -column "$AUDIT_DB" \
  "SELECT id,
          llm_backend AS resolved_backend,
          json_extract(config_json, '$.llm_backend') AS config_override,
          datetime(created_at, 'unixepoch') AS created_utc,
          datetime(completed_at, 'unixepoch') AS completed_utc
   FROM runs
   WHERE id IN (
     'd58f0e54-cd9c-4aaa-8865-6e41f77ad343',
     'e09f380d-6f6e-4f94-a544-f671f44bd7e7'
   );"
```

The second command returned `offline`/`NULL` for `resolved_backend`/`config_override` on both rows, with the UTC timestamps recorded above.

```sql
SELECT r.id,
       (SELECT COUNT(*) FROM hypotheses h WHERE h.run_id = r.id) AS hypotheses,
       (SELECT COUNT(*) FROM evidence e WHERE e.run_id = r.id) AS evidence,
       (SELECT COUNT(*) FROM matches m WHERE m.run_id = r.id) AS matches,
       (SELECT COUNT(*) FROM claim_evidence c
        WHERE c.run_id = r.id AND c.label = 'insufficient') AS insufficient_claims
FROM runs r
WHERE r.id IN (
  'd58f0e54-cd9c-4aaa-8865-6e41f77ad343',
  'e09f380d-6f6e-4f94-a544-f671f44bd7e7'
);

SELECT run_id, stage, decision, COUNT(*)
FROM safety_decisions
WHERE run_id IN (
  'd58f0e54-cd9c-4aaa-8865-6e41f77ad343',
  'e09f380d-6f6e-4f94-a544-f671f44bd7e7'
)
GROUP BY run_id, stage, decision;

SELECT h.run_id, hs.status, hs.safety_status, COUNT(*)
FROM hypothesis_state hs
JOIN hypotheses h ON h.id = hs.hypothesis_id
WHERE h.run_id IN (
  'd58f0e54-cd9c-4aaa-8865-6e41f77ad343',
  'e09f380d-6f6e-4f94-a544-f671f44bd7e7'
)
GROUP BY h.run_id, hs.status, hs.safety_status;

SELECT r.id,
       ROUND(r.completed_at - r.created_at, 3) AS wall_seconds,
       json_extract(p.payload_json, '$.execution_time')
         AS report_execution_seconds,
       json_array_length(
         json_extract(p.payload_json, '$.idea_buckets.high_potential')
       ) AS high_potential,
       json_array_length(
         json_extract(p.payload_json, '$.idea_buckets.non_viable')
       ) AS non_viable,
       json_extract(p.payload_json, '$.hypothesis_count')
         AS report_hypotheses,
       json_extract(p.payload_json, '$.evidence_count')
         AS report_evidence,
       json_extract(p.payload_json, '$.match_count')
         AS report_matches,
       json_array_length(json_extract(p.payload_json, '$.leaderboard'))
         AS leaderboard_count,
       json_array_length(json_extract(p.payload_json, '$.claim_evidence'))
         AS report_claim_rows
FROM runs r
JOIN reports p ON p.run_id = r.id
WHERE r.id IN (
  'd58f0e54-cd9c-4aaa-8865-6e41f77ad343',
  'e09f380d-6f6e-4f94-a544-f671f44bd7e7'
);
```

The claim-gate counts are the `stage='claim_gate' AND decision='block'` groups returned by the `safety_decisions` query. The report hashes were produced exactly as follows; `sqlite3` adds the trailing newline included in each hash:

```bash
AUDIT_DB=/tmp/cosci-fidelity-audit.PVBi1v/coscientist.db

for RUN_ID in \
  d58f0e54-cd9c-4aaa-8865-6e41f77ad343 \
  e09f380d-6f6e-4f94-a544-f671f44bd7e7
do
  sqlite3 "$AUDIT_DB" \
    "SELECT payload_json FROM reports WHERE run_id='$RUN_ID';" \
    | shasum -a 256
  sqlite3 "$AUDIT_DB" \
    "SELECT markdown_text FROM reports WHERE run_id='$RUN_ID';" \
    | shasum -a 256
done
```
