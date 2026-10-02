# Frontend loading performance — 2 October 2026

The initial JavaScript entry eagerly loaded report pages, Markdown parsing and
syntax highlighting. Route and prose boundaries now defer those modules until
they are needed. The home and provider/layout topology stays intact. A direct
route displays a loading status inside the shell; navigation transitions keep
the current page while the selected route downloads.

`markdown_message.tsx` remains the public prose component. Its pending fallback
shows escaped, wrapping plain text and follows streaming updates. A local error
boundary preserves the current text and workspace if formatting cannot load,
with a reload action. The extracted `markdown_message_renderer.tsx` preserves
the original renderer apart from its export name: raw HTML remains ignored,
highlighting and code-copy controls remain available, and completed streamed
blocks retain memoization. Failed route imports use the existing application
error boundary's reload recovery.

## Emitted artifacts

Baseline source: `af656a915aa9ffe58bf678ed0815f1cf4a160d52`. Both builds use
the same committed dependency lock, Bun 1.3.14, Node 24.19.0 and Vite 7.3.6.
These are exact emitted-file bytes, compressed with Node's
`zlib.gzipSync(data, {level: 9})`. They supersede exploratory Rollup-hook and
default-level console estimates.

| Artifact | Baseline bytes | Baseline gzip bytes | Updated bytes | Updated gzip bytes |
| --- | ---: | ---: | ---: | ---: |
| Initial JavaScript entry | 957,300 | 293,309 | 527,286 | 163,561 |
| Home landing chunk | 32,665 | 11,067 | 32,665 | 11,068 |
| CSS | 130,429 | 23,803 | 130,429 | 23,803 |

The entry saves 129,748 gzip bytes, **44.23%**. A visit that displays rich prose
still downloads its renderer; this is an initial-entry reduction, not a claim
about total bytes for every visit. The entry still exceeds Vite's 500 kB raw
warning threshold. No warning threshold, highlighting languages, package,
dependency bound, lock, stylesheet or manual chunk configuration was changed.

| Deferred JavaScript | Bytes | Gzip bytes |
| --- | ---: | ---: |
| Markdown renderer and highlighting | 340,113 | 103,470 |
| Run detail | 85,473 | 25,613 |
| Shared report | 2,413 | 1,034 |
| Researcher access | 1,650 | 895 |
| Shared run-collections helper | 1,291 | 540 |

Route-only deferral saved about 26 kB of initial gzip in the exploratory build.
Deferring the full renderer preserves its current features and gives a larger
reduction. Snapshot requests already run in parallel, so no fetching change was
justified. Existing metadata/noscript prerendering still succeeds; this
application uses `createRoot`, and a future server-rendered setup would need
its own Suspense/hydration design.

## Laboratory timing

Three fresh Chromium contexts per route were measured for each build, with the
baseline immediately before the final build using the same local gzip server
and harness. Chromium 151.0.7922.173 used a 390×844 viewport, 4× CPU throttle,
150 ms network latency, 200,000 B/s download and 93,750 B/s upload. APIs returned
empty local fixtures, external requests were blocked, and samples settled after
network-idle plus 1.5 seconds. Timing runs did not collect V8 coverage.

| Route and median metric | Baseline milliseconds | Updated milliseconds |
| --- | ---: | ---: |
| Home first contentful paint | 2,496 | 1,876 |
| Home largest contentful paint | 3,320 | 2,660 |
| Access first contentful paint | 2,416 | 1,664 |
| Access largest contentful paint | 2,416 | 1,908 |

No page errors occurred in these samples. Home long-task totals were essentially
unchanged (838 vs. 839 ms); the evidence supports less initial download and
earlier paint, not an overall CPU improvement. This is a small local laboratory
sample on a shared host, not production field data. Existing chats that require
Markdown, loaded reports, real research data and provider/backend latency were
not profiled. Recheck those workloads before further splitting the bundle.

## Validation

Original renderer tests keep their semantic assertions and exercise the
extracted renderer directly. New public-boundary tests verify deferred imports,
pending updates, escaped HTML, successful formatting and readable failure
fallbacks. Route tests cover deferral, loading, persistent shell and rejected
downloads. Existing assistant-bubble and plan-card tests await actual
formatting while preserving their assertions.

All 896 frontend tests across 134 files passed. The terminal-history polling
test now waits for committed history and flushes timer-driven React updates
before measuring settled calls, preserving its existing stop-poll assertion.
Frontend lint, TypeScript/production build and metadata prerender passed.
Both isolated offline browser suites passed: 18 workbench cases and three
built-asset/authentication cases. The parity gate resolved all 115 rows,
214 evaluation tests passed, and the offline safety/citation smoke passed.
No live provider-backed run or production performance measurement was made.
