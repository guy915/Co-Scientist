import {useLayoutEffect, useRef} from 'react';

// True when the node's content no longer fits its box on the axis being
// tested for the current `lines` setting (a 1px slack absorbs subpixel
// rounding so borderline fits don't falsely register as overflow).
function overflows(node: HTMLSpanElement, lines: number): boolean {
  return lines > 1
    ? node.scrollHeight > node.clientHeight + 1
    : node.scrollWidth > node.clientWidth + 1;
}

// Rewrites `node.textContent` to `text`, or if that overflows, to the
// longest word-truncated "word…" prefix of `text` that fits. Binary-searches
// the word count. Every probe forces a synchronous reflow (write textContent,
// read scroll size), so the search must be O(log words), not one word at a
// time — long labels in long lists (the ideas rank list) otherwise stack
// hundreds of reflows into a single commit and stall tab switches for ~a
// second.
function fitTruncatedText(
  node: HTMLSpanElement,
  text: string,
  lines: number,
): void {
  node.textContent = text;
  if (!overflows(node, lines)) return;
  const words = text.split(/\s+/).filter(Boolean);
  let lo = 1;
  let hi = words.length - 1;
  let best = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    node.textContent = `${words.slice(0, mid).join(' ')}…`;
    if (overflows(node, lines)) {
      hi = mid - 1;
    } else {
      best = mid;
      lo = mid + 1;
    }
  }
  // best === 0: even the first word alone is too wide — clip it.
  node.textContent = `${words.slice(0, Math.max(best, 1)).join(' ')}…`;
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

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    function fit() {
      const node = ref.current;
      if (!node) return;
      fitTruncatedText(node, text, lines);
    }

    // Fit synchronously, again on the next frame (the first paint can measure
    // before the rail's flex/grid layout has settled), and once more after web
    // fonts load (which changes text metrics). A ResizeObserver keeps it
    // correct on later width changes.
    fit();
    const raf = requestAnimationFrame(fit);
    let cancelled = false;
    void document.fonts?.ready.then(() => {
      if (!cancelled) fit();
    });
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    // A tab that loads in the background suspends rAF/ResizeObserver, so the
    // first fit can run against an unsettled width; re-fit when it foregrounds.
    const onVisible = () => {
      if (!document.hidden) fit();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      observer.disconnect();
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [text, lines]);

  // No children: fit() owns this node's textContent directly.
  return <span ref={ref} className={className} />;
}
