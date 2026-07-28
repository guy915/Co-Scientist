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
export function requestFit(
  node: HTMLSpanElement,
  text: string,
  lines: number,
): void {
  node.textContent = text;
  pending.set(node, {node, text, lines});
  if (flushQueued) return;
  flushQueued = true;
  queueMicrotask(flushPendingFits);
}
