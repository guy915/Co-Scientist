import {type RefObject, useLayoutEffect, useRef} from 'react';

// Schedules `fit` immediately, again on the next animation frame (the
// first paint can measure before the rail's flex/grid layout has settled),
// once more after web fonts load (which changes text metrics), on any
// resize of `el`, and again whenever a backgrounded tab foregrounds (rAF and
// ResizeObserver are suspended while hidden, so the first fit can run
// against an unsettled width). Returns a cleanup that cancels every one of
// those.
function scheduleFits(fit: () => void, el: HTMLSpanElement): () => void {
  fit();
  const raf = requestAnimationFrame(fit);
  let cancelled = false;
  void document.fonts?.ready.then(() => {
    if (!cancelled) fit();
  });
  // The re-fit is deferred to the next frame rather than run inside the
  // observer callback: fit() rewrites the observed node's own text, so a
  // synchronous call resizes an element in the middle of the delivery it
  // was triggered by. The browser reports that as an uncaught
  // "ResizeObserver loop completed with undelivered notifications" error,
  // which the UI error logger then persists — dozens of ERROR rows a
  // second on any list of truncated labels. Deferring keeps the write out
  // of the observation cycle, and fit() is idempotent for a given width,
  // so the next frame settles instead of oscillating.
  let queued = 0;
  const observer = new ResizeObserver(() => {
    cancelAnimationFrame(queued);
    queued = requestAnimationFrame(fit);
  });
  observer.observe(el);
  const onVisible = () => {
    if (!document.hidden) fit();
  };
  document.addEventListener('visibilitychange', onVisible);
  return () => {
    cancelled = true;
    cancelAnimationFrame(raf);
    cancelAnimationFrame(queued);
    observer.disconnect();
    document.removeEventListener('visibilitychange', onVisible);
  };
}

// Keeps `ref`'s span fitted to `text` across every
// event that can change what fits: mount, next-frame layout settle, web-font
// load, container resize, and tab foregrounding. Extracted verbatim from the
// component so TruncatedLabel itself stays a thin render — the
// scheduling/timing in scheduleFits is deliberate (see its comments) and
// must not change.
//
// Each of those triggers only *enqueues* the fit; the measurement itself runs
// in a batch a microtask later (still before paint), so every label mounted or
// resized together shares one set of layout flushes instead of forcing its
// own. See the batched fitting helpers below for why that matters.
function useTruncatedFit(
  ref: RefObject<HTMLSpanElement | null>,
  text: string,
  lines: number,
) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    function fit() {
      const node = ref.current;
      if (!node) return;
      requestFit(node, text, lines);
    }

    return scheduleFits(fit, el);
  }, [ref, text, lines]);
}

/**
 * Label that truncates on word boundaries: when the text does not fit
 * its container it drops whole trailing words and appends a single
 * ellipsis, so the result is always "word…" — never a mid-word cut
 * ("wor…") or a dangling space ("word …"), which is what CSS
 * `text-overflow: ellipsis` and `-webkit-line-clamp` produce. The only
 * exception is a first word itself wider than the container, which
 * must be clipped.
 *
 * `lines` selects the fit test: 1 (default) measures width against a single
 * nowrap line; a value > 1 measures height, relying on the host's own clamp
 * (`-webkit-line-clamp` / a fixed max-height) to bound `clientHeight`. The
 * exact visible line count therefore comes from the host CSS, not this prop.
 *
 * The visible text is owned imperatively (the span renders no React children),
 * so measurement can rewrite it freely without fighting reconciliation. A
 * ResizeObserver re-fits on size changes (rail collapse, window resize).
 *
 * The host element must constrain the relevant axis and hide overflow
 * — for one line `min-width: 0; overflow: hidden; white-space:
 * nowrap`; for multiple, a clamped box such as `display: -webkit-box;
 * -webkit-line-clamp: N; overflow: hidden`.
 */
export function TruncatedLabel({
  text,
  className,
  lines = 1,
}: {
  text: string;
  className?: string;
  lines?: number;
}) {
  // Holds the span whose textContent is rewritten imperatively by fit();
  // React never re-renders text into this node (see the bare <span> below).
  const ref = useRef<HTMLSpanElement>(null);
  useTruncatedFit(ref, text, lines);

  // No children: fit() owns this node's textContent directly.
  return <span ref={ref} className={className} />;
}

/**
 * Batched word-boundary text fitting for {@link TruncatedLabel}.
 *
 * Fitting one label means probing: write a candidate string, then read a
 * scroll size to see whether it still overflows. The read forces the browser
 * to flush layout, so a probe costs a full layout pass -- and fitting labels
 * one after another interleaves write/read/write/read, paying that pass for
 * every single probe. On the ideas tab (21 rows x 2 labels) that was ~127
 * forced layouts in one commit: two ~390ms blocking tasks, i.e. the entire
 * cost of opening the tab.
 *
 * So probing is batched instead. Every label registers its request, and one
 * flush runs the binary searches in lockstep: all labels write round N's
 * candidate, then all labels read. Layout is flushed once per round rather
 * than once per probe, which is log2(words) passes for the whole page instead
 * of sum(log2(words)) -- 4 instead of 127, and ~12ms instead of ~125ms.
 *
 * The flush is a microtask, so it lands after every label mounted in the same
 * commit has registered but still before the browser paints: batching costs
 * no frame and shows no flash of unfitted text.
 */

/** One label's outstanding request to be fitted. */
interface FitRequest {
  node: HTMLSpanElement;
  text: string;
  lines: number;
}

/** In-progress binary search over one label's word count. */
interface FitJob {
  node: HTMLSpanElement;
  lines: number;
  words: string[];
  // Word-count search bounds, the candidate under test, and the largest count
  // known to fit so far (0 until one does).
  lo: number;
  hi: number;
  mid: number;
  best: number;
}

// True when the node's content no longer fits its box on the axis being
// tested for the current `lines` setting (a 1px slack absorbs subpixel
// rounding so borderline fits don't falsely register as overflow).
function overflows(node: HTMLSpanElement, lines: number): boolean {
  return lines > 1
    ? node.scrollHeight > node.clientHeight + 1
    : node.scrollWidth > node.clientWidth + 1;
}

/** The first `count` words of `job`, with the trailing ellipsis. */
function candidate(job: FitJob, count: number): string {
  return `${job.words.slice(0, count).join(' ')}…`;
}

// Writes every request's full text, then reads every request's overflow, and
// returns a search job for each label that actually needs truncating. Split
// into a write pass and a read pass for the same reason the probe rounds are:
// one layout flush for the whole batch instead of one per label.
function startJobs(requests: readonly FitRequest[]): FitJob[] {
  for (const request of requests) request.node.textContent = request.text;
  const jobs: FitJob[] = [];
  for (const request of requests) {
    if (!overflows(request.node, request.lines)) continue;
    const words = request.text.split(/\s+/).filter(Boolean);
    jobs.push({
      node: request.node,
      lines: request.lines,
      words,
      lo: 1,
      hi: words.length - 1,
      mid: 0,
      best: 0,
    });
  }
  return jobs;
}

// Advances every job by one binary-search step -- all writes, then all reads
// -- and returns those still searching.
function probeRound(jobs: readonly FitJob[]): FitJob[] {
  for (const job of jobs) {
    job.mid = (job.lo + job.hi) >> 1;
    job.node.textContent = candidate(job, job.mid);
  }
  for (const job of jobs) {
    if (overflows(job.node, job.lines)) {
      job.hi = job.mid - 1;
    } else {
      job.best = job.mid;
      job.lo = job.mid + 1;
    }
  }
  return jobs.filter(job => job.lo <= job.hi);
}

/** Writes a finished job's longest fitting prefix. */
function commitJob(job: FitJob): void {
  // best === 0: even the first word alone is too wide — clip it.
  job.node.textContent = candidate(job, Math.max(job.best, 1));
}

/**
 * Fits every request to its container in lockstep. Exported for the tests,
 * which drive it directly rather than through the microtask scheduler.
 */
export function fitAll(requests: readonly FitRequest[]): void {
  const jobs = startJobs(requests);
  let searching: readonly FitJob[] = jobs;
  while (searching.length) searching = probeRound(searching);
  for (const job of jobs) commitJob(job);
}

// Requests awaiting the next flush, keyed by node so the repeated fits one
// label schedules (mount, next frame, font load, resize, tab foreground)
// collapse into its latest one.
const pending = new Map<HTMLSpanElement, FitRequest>();
let flushQueued = false;

/** Runs every pending fit as one batch, dropping unmounted labels. */
export function flushPendingFits(): void {
  flushQueued = false;
  const requests = [...pending.values()].filter(
    request => request.node.isConnected,
  );
  pending.clear();
  if (requests.length) fitAll(requests);
}

/**
 * Queues `node` to be fitted to `text` in the next batch. Idempotent per node
 * within a batch: the last call before the flush is the one that runs.
 *
 * The full text is written straight away and only the *measuring* is batched,
 * so the node never holds another label's text or a stale one while it waits
 * its turn — it holds the untruncated version of what it is about to show,
 * which is also what it settles on wherever nothing overflows.
 */
function requestFit(node: HTMLSpanElement, text: string, lines: number): void {
  node.textContent = text;
  pending.set(node, {node, text, lines});
  if (flushQueued) return;
  flushQueued = true;
  queueMicrotask(flushPendingFits);
}
