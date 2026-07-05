import {useLayoutEffect, useRef} from 'react';

/**
 * Single-line label that truncates on word boundaries: when the text does not
 * fit its container it drops whole trailing words and appends an ellipsis, so a
 * word is never cut mid-way (unlike CSS `text-overflow: ellipsis`). The only
 * exception is a first word that is itself wider than the container, which must
 * be clipped.
 *
 * The visible text is owned imperatively (the span renders no React children),
 * so measurement can rewrite it freely without fighting reconciliation. A
 * ResizeObserver re-fits on width changes (rail collapse, window resize).
 *
 * The host element must constrain width and hide overflow (e.g. `min-width: 0;
 * overflow: hidden; white-space: nowrap`).
 */
export function TruncatedLabel({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    function fit() {
      const node = ref.current;
      if (!node) return;
      node.textContent = text;
      if (node.scrollWidth <= node.clientWidth) return;
      const words = text.split(/\s+/).filter(Boolean);
      for (let n = words.length - 1; n >= 1; n--) {
        node.textContent = `${words.slice(0, n).join(' ')}…`;
        if (node.scrollWidth <= node.clientWidth) return;
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
  }, [text]);

  return <span ref={ref} className={className} />;
}
