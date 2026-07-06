import {useLayoutEffect, useRef} from 'react';

/**
 * Label that truncates on word boundaries: when the text does not fit its
 * container it drops whole trailing words and appends a single ellipsis, so the
 * result is always "word…" — never a mid-word cut ("wor…") or a dangling space
 * ("word …"), which is what CSS `text-overflow: ellipsis` and
 * `-webkit-line-clamp` produce. The only exception is a first word itself wider
 * than the container, which must be clipped.
 *
 * `lines` selects the fit test: 1 (default) measures width against a single
 * nowrap line; a value > 1 measures height, relying on the host's own clamp
 * (`-webkit-line-clamp` / a fixed max-height) to bound `clientHeight`. The exact
 * visible line count therefore comes from the host CSS, not this prop.
 *
 * The visible text is owned imperatively (the span renders no React children),
 * so measurement can rewrite it freely without fighting reconciliation. A
 * ResizeObserver re-fits on size changes (rail collapse, window resize).
 *
 * The host element must constrain the relevant axis and hide overflow — for one
 * line `min-width: 0; overflow: hidden; white-space: nowrap`; for multiple, a
 * clamped box such as `display: -webkit-box; -webkit-line-clamp: N; overflow:
 * hidden`.
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
  const ref = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    const overflows = (node: HTMLSpanElement) =>
      lines > 1
        ? node.scrollHeight > node.clientHeight + 1
        : node.scrollWidth > node.clientWidth + 1;

    function fit() {
      const node = ref.current;
      if (!node) return;
      node.textContent = text;
      if (!overflows(node)) return;
      const words = text.split(/\s+/).filter(Boolean);
      for (let n = words.length - 1; n >= 1; n--) {
        node.textContent = `${words.slice(0, n).join(' ')}…`;
        if (!overflows(node)) return;
      }
      // A single word too wide to fit: clip it with an ellipsis.
      node.textContent = `${words[0] ?? ''}…`;
    }

    // Fit synchronously, again on the next frame (the first paint can measure
    // before the rail's flex/grid layout has settled), and once more after web
    // fonts load (which changes text metrics). A ResizeObserver keeps it correct
    // on later width changes.
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

  return <span ref={ref} className={className} />;
}
