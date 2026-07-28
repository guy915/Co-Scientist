import type {RefObject} from 'react';
import {useLayoutEffect, useRef} from 'react';
import {requestFit} from './truncated_label_fit';

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

// Keeps `ref`'s span fitted to `text` (see truncated_label_fit) across every
// event that can change what fits: mount, next-frame layout settle, web-font
// load, container resize, and tab foregrounding. Extracted verbatim from the
// component so TruncatedLabel itself stays a thin render — the
// scheduling/timing in scheduleFits is deliberate (see its comments) and
// must not change.
//
// Each of those triggers only *enqueues* the fit; the measurement itself runs
// in a batch a microtask later (still before paint), so every label mounted or
// resized together shares one set of layout flushes instead of forcing its
// own. See truncated_label_fit for why that matters.
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
