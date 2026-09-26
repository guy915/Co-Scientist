# Ling Fin bounded interface assessment

**Disposition:** interface-compatible provisional candidate. This is a local design choice and external route test, not Google-backed behavior or scientific-quality qualification. No default, fallback or production setting changed.

The [fresh credential-free admission](ling-fin-preflight-v1.json) at 2026-09-26 09:47 UTC found `inclusionai/ling-3.0-flash-fin:free` at zero catalog prompt/completion price, one available-status Novita endpoint at zero prompt/completion price and a matching exact endpoint in OpenRouter's ZDR inventory. The public metadata does not expose a verified per-request price; every live request carried the binding `max_price.request=0` control. The [frozen protocol](ling-fin-qualification-prereg-v1.json) had SHA256 `fdd792589cfe976eec622608546afb0af56a1d0de5c2cee8e5981d18e65852a8` before inference; its runner checked that literal, the pinned source/input hashes and the committed launch revision `531a53ec01fd7781312e0544034855874213ce62` before transport. The output path did not exist before the launch.

The single [raw bounded panel](ling-fin-bounded-panel-v1.json) began at 09:48 UTC and completed all six cases under the seven-call ceiling:

| Case | Physical requests | Observed behavior |
| --- | ---: | --- |
| Schema JSON, thinking requested off | 1 | Valid locally checked JSON, exact supporting quote. |
| Schema JSON, thinking requested on | 1 | Same schema and quote passed. |
| Plain JSON | 1 | Valid object and quote; `SUPPORTS` was accepted case-insensitively because this prompt has no enum. |
| Tool round trip | 2 | Called local synthetic `lookup_measurement(control-A)` once and included its returned `137` in the final answer. |
| App streaming | 1 | Four content deltas, `stop`, SDK model field and prompt/completion usage chunk. |
| Long schema JSON | 1 | Valid quote-backed response to a 126,555-character prompt. |

All seven observed request payloads used the exact Fin route, Novita-only provider pin, `allow_fallbacks=false`, `zdr=true`, `data_collection=deny`, `require_parameters=true`, and zero prompt/completion/request caps. The five nonstream cases reported the requested/observed model and complete token usage with zero static estimated cost, no unpriced or unobserved calls, and no recorded deterministic fallback. The streaming case reported its model and usage through SDK chunks; its engine telemetry had no streaming usage row, so it has no static cost estimate or independent provider/billing receipt. The stream request still carried the same zero-price controls. No credential-shaped value is present in the retained artifacts.

The “thinking off” cases went out with bounded reasoning enabled (`max_tokens=2048`) because this route is declared unable to disable reasoning; “thinking on” used high effort. Thus the panel verifies both application request paths, not literal reasoning-disable support. The tool's diagnostic “no registry entry” warning did not prevent its synthetic executor invocation or final answer, but this case does not validate a scientific connector. The zero-cost controls and public prices establish bounded eligibility, not actual billing statements. Scientific claim-grounding, citation, usefulness, ranking and a real public workflow remain untested for Fin. The next authorized gate is the preregistered three-trial four-claim batch screen; no larger panel or default switch precedes its result.

The streaming usage chunk also reports 417 reasoning tokens beside 33 total tokens. That arithmetic is inconsistent, so the stream token breakdown cannot support a measured cost or reasoning-efficiency claim; it only shows that prompt/completion usage fields were returned. An independent Luna 6 xhigh audit found no blocker to the frozen interface gate and confirmed that scientific selection remains separate.
