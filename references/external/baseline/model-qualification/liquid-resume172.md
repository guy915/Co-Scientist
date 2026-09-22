# Liquid scientific qualification resume 172

Run date: 2026-09-22 UTC. The provider reset was rechecked before launch. A fresh OpenRouter catalog read accepted `liquid/lfm-2.5-2.6b:free` with prompt and completion pricing `0`. The existing citation-panel probe was run in a strict isolated child environment with only the in-memory extracted OpenRouter credential, `PYTHON_DOTENV_DISABLED=1`, `COSCIENTIST_REQUIRE_FREE_MODELS=1`, `COSCIENTIST_CACHE_ENABLED=0`, and no paid route or fallback.

The three trials ran sequentially in parent session `88388` (parent PID `97621`; child PIDs `97622`, `7483`, `41406`). The runner completed all three and exited after trial 3. No live duplicate probe was present before launch. Logs remain outside the repository at `/private/tmp/coscientist-liquid-challenge172-{1,2,3}.log`.

All artifacts use the current arm of `pro-current-sources163.json`, with 585 frozen source hashes:

- source commit: `ee77507415a248889683cef551ec1dd083645bb4`
- probe SHA256: `6f180906b01e384722747abf251b83d7f161b01f38998a03559630f3db4e69d1`
- manifest SHA256: `06344a84e7696f4d7719a4569f7bca7ae90a182643701b18038b0fe4e487c740`
- source-guard SHA256: `64edc5d5f57f6594ea0cdf9836c9a9a302a21b51e18faa0ccc1c76c04541238c`
- challenge SHA256: `1636ddcfb94084ccabe5f155fd5701c3270c7ffc751e1c16a6450cece61c39f2`

| Trial | Physical requests | Accuracy | Contradiction recall | Gates | Historical | Scope controls |
| --- | ---: | ---: | ---: | --- | --- | --- |
| 1 | 74 | 0.533 | 0.100 | fail | pass | 15/20 |
| 2 | 84 | 0.500 | 0.000 | fail | pass | 12/20 |
| 3 | 75 | 0.600 | 0.200 | fail | pass | 13/20 |

The unchanged production gates were accuracy `0.75` and contradiction recall `0.80`; all three trials fail both. The controlled-primary checks passed in all three trials. Every recorded request carried zero prompt, completion and request caps, and all observed responses used the requested Liquid route. Trial logs retain upstream 429 observations (8, 26 and 12 respectively), deterministic-assessor fallback events (1, 3 and 2), and two schema-validation retry sequences in trial 3. These are operational/model behavior evidence, not threshold changes. The raw artifacts are retained without rejection or acceptance claims.

Artifacts: `liquid-challenge172-1.json`, `liquid-challenge172-2.json`, and `liquid-challenge172-3.json`.
