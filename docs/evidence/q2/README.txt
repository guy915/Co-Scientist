Q2 launch cross-browser and keyboard evidence
Repository guy915/Co-Scientist; board #453; live register6057496579.
Setup: Bun1.3.14 plus bunx, make setup0. Production Vite assets served over isolated fresh offline SQLite stores; dotenv disabled, evidence resolver offline, unreachable MCP. No live model/provider, production data or hosting change.
Playwright1.61.1 engines: desktop WebKit1440x900, WebKit iPhone14/device390x664, Firefox1440x900, light/dark. Native Tab/Shift+Tab/Enter/Space/Escape/arrows/Home/End, DOM accessible-role/name snapshots, axe and live-region mutations. This does not claim physical iPhone, VoiceOver or Firefox screen-reader speech testing.

Open lane-q2-browser-evidence.zip, extract it and open index.html for the local screenshot gallery. manifest.json records every included PNG/YAML/JSON and its SHA256. 22 root before/after PNGs and three closed-observation controls are duplicated for inline board viewing; the ZIP gallery curates these plus12 final keyboard home/report screenshots. receipts.json records immutable source revisions, real gate exits and original-source controls.
Only synthetic local goals/IDs are included. No trace, request body, database, environment, credential or raw server log is published.

before/: initial first-visitor baseline tours and original keyboard menu failures.
announcements-tour/: complete final pointer/keyboard tours: accessible snapshots and whole-page axe/live/native-error JSON for every stage; curated keyboard home/report PNGs for every browser/theme. Full raw screenshots remain in local scratch.
final-guard-latest/: final44 targeted native production cases and their accessible/screenshot evidence.
final-guard-complete/: earlier36-case passing checkpoint, before the two late landing findings.
progress-before/: original ordinary task-status snapshot.
scroll-before/sections-before/: original-source keyboard-scroll/landmark failures.
navigation-diagnostics*/: classified WebKit canceled best-effort telemetry, native-DOM zero-exception observers and deliberate thrown-exception canary.
contrast-observation/contrast-visible-final/: raw offscreen sliding-background observation and visible Landing-navigation/Standard whole-page controls.
reconnect-before/reconnect-entry-before/: original light status2.13:1 and entry text3.43:1 color failures; originals retained.
reconnect-entry-after/: corrected warning foreground/shared text entry at a paused20% animation frame, all engines/themes.
headings-before/headings-after/: specification h2→h4 failure and corrected h2→h3 with reload across all engines/themes.

Gates/fixes:
#532 menu autofocus/arrows/Escape/Tab: all five then-required direct gates0;74 Chromium cases0;6 new engine guards0; exact-green squash42d81f5c.
#546 named banner/conversation h1: all five direct gates0;87 Chromium cases0;12 integrated menu/semantic guards0; original source fails; exact-green squash1a579098.
#552 settled-reply/task progress announcements: all five direct gates0;91 Chromium cases0;18 integrated guards0; original reply/progress controls fail; exact-green squashe431d3da on446af10a. Persistent polite replies are quiet on history/reload, ignore partial/reasoning/failure, and announce each new settled interview/run-start/Q&A reply once. Task/count updates are atomic polite statuses; elapsed clock is outside them.
#560 active keyboard scroll/report sections: all five direct gates0;91 Chromium cases0;12 new engine guards0; both original controls fail; exact-green squash5ecddea0 on5482b099.
P#555 footer hierarchy: exact-green squash34ab165a; Q2-09 closed through owner fix.
#583 activity contrast: actual final make presubmit0/592.72s;350frontend,115development,15production; exact-green squashb742b40b onededdabf8.
#587 specification heading order: actual final make presubmit0/849.47s;350frontend,115development,17production; exact-green squash29a2505f on8fb575f1.
#601 visible landing-navigation transition contrast: actual final make presubmit0/725.44s;360frontend,119development,19production. Exact-green squash ec9c38d7 on7301a179. Original actual visible Tiers4.21:1 in both desktop light controls; active links now change their own background and foreground together.
#602 native landing-rail focus: actual final make presubmit0/627.77s;360frontend,119development,21production on locally frozen b521a858/tree91d8985d, published48c89d2e. Restores the focused section in the visible copy when its original becomes inert; respects focus moved to another control. Exact-green squash27fc775f, all21 checks complete/applicable SUCCESS.
Final44 tagged cases and12 full first-visitor journeys use frozen b521a858/main ec9c38d7, including P#596 recipient notices, O#599 backup controls and S4#597 CSP. Frontend tree01dca766cc7f9b3fcfb64f41524cdadafd85001e; engine3b18d1e68189212320f536a754beb3c15063385d. Real exit/duration/source receipts are in receipts.json. Later unrelated merges/dependency updates are not silently included. Earlier passing36/12 checkpoint on2e555bf0 is retained separately. Each published source PR tree matches its locally checked tree.

Retained failed attempts: initial menu1.34px alignment led to preventScroll; semantic browser stale P/legal assertion integrated P#540; announcement visible-text query ambiguity resolved in unheld announcer context/selectors; initial new e2e guard TypeScript timing.delay optional error corrected with zero default; a new worktree initially lacked frontend tsc (build127) before locked install. The first final tour attempt's overbroad WebKit engine-pageerror assertion stopped it, one port-busy restart failed1, then corrected native-DOM-observer tour passed12/12. These are distinct from corrected product gates.

Closed observations: Q2-02 native keyboard discovery-helper reparent/browser-chrome traversal, corrected directional journey reaches FAQ; separate later Q2-15 confirms actual native copy-handoff focus loss; Q2-10 WebKit engine canceled-fetch diagnostic classification, zero native exceptions plus detected canary; Q2-11 offscreen Standard sliding-background measurement; settled visible controls pass. Separate Q2-14 demonstrates the actual visible transition failure and fixes it. Raw observations remain in the archive, rather than excluding contrast rules. The final source fixes Q2-12's actual row/status contrast and Q2-13's actual static heading order. Linked Q/U duplicate items remain with their owners; this is Q2 closure, not approval of P's controller/legal/retention decisions or the overall launch.

Additional retained attempts: contrast concurrent presubmit repeat2 (349frontend pass/one T-owned linked-draft recovery failure), then uncontended actual full presubmit0. Earlier combined36 fixture run stopped130 after paused animation translation caused native WebKit Home1px; the fixture finishes actual animations before strict Home0, while contrast remains checked at20%. A separate overbroad scratch tour stopped130 after four genuine WebKit desktop journeys passed and two obsolete pre-fix menu discovery assertions failed; final command explicitly selects first visitor only. No timeout, product assertion or axe rule was weakened. Original before-menu PNG/JSON were recovered byte-for-byte from the earlier preserved ZIP after the obsolete scratch case wrote its old baseline output path.

footer-before/footer-after: actual original P#555 parent footer hierarchy fails both theme controls1; corrected named navigation controls0.
final-guard36/: structured evidence of the interrupted paused-animation attempt, explicitly not a complete passing matrix.
Archive excludes hidden Playwright resource/traces, databases, raw logs, request bodies and environment. SHA256 manifest is exhaustive for every curated file.

Final actual results and durations: see receipts.json. Final matrices select44 tagged cases and12 first-visitor cases. All native-DOM exception/rejection and horizontal-overflow assertions remain strict. Desktop marketing/FAQ and phone home/drawer reflect the responsive product; only desktop marketing rail specs are excluded on phone.

landing-transition-before/: actual visible original color-transition failure, geometry/animations/axe at50%, light and dark desktop controls.
landing-transition-after/: corrected contrast prototype; all four contrast scans empty but focus predicates fail1. Retained as before-source evidence for the separate Q2-15.
landing-focus-control/: direct chronology confirms document.hasFocus=true and body focus immediately after copy handoff, before screenshot/axe; successful recording is not a passing product focus assertion.
landing-focus-after/: initial four native focus controls0; final44 includes the later outside-focus fence.
Additional actual failed driver: initial #601 presubmit2 at e2e NodeList compilation after first seven commands0; Array.from corrected the source and actual frontend-local e2e compiler0/full final presubmit0 followed. One ref update used an incorrect branch spelling and was rejected; the existing PR branch was inspected and the expected-head fast-forward succeeded. Neither rejection is a test pass. No source reset/amend/stash/restore.
