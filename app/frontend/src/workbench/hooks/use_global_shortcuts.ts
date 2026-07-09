import {useEffect} from 'react';
import {useLocation, useNavigate} from 'react-router-dom';

/**
 * Global keyboard shortcuts:
 *   g n  -> /
 *   ←/→  -> cycle tabs on /runs/:id
 * Inputs and textareas are ignored so typing doesn't trigger the bindings.
 */
// Arrow-key cycling order; must match the tab routes RunDetail renders.
const TABS = ['details', 'learning', 'overview', 'ideas'] as const;

// True when the key event originated in an editable control (input,
// textarea, contenteditable), in which case shortcuts must not fire.
function isTextEditingTarget(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
}

// Resolves an ArrowLeft/ArrowRight press on a /runs/:id(/:tab) route to the
// path for the adjacent tab, or null when the key/route doesn't apply or the
// current tab is already at that end of TABS (no wraparound).
function nextTabPath(pathname: string, key: string): string | null {
  if (key !== 'ArrowLeft' && key !== 'ArrowRight') return null;
  const m = pathname.match(/^\/runs\/([^/]+)(?:\/(.+))?$/);
  if (!m) return null;
  const id = m[1];
  if (id === 'new') return null; // legacy path, not a real run
  // Unknown or missing tab segments count as the default 'details'.
  const current = (
    m[2] && (TABS as readonly string[]).includes(m[2]) ? m[2] : 'details'
  ) as (typeof TABS)[number];
  const idx = TABS.indexOf(current);
  // Clamp at the ends rather than wrapping around.
  const next =
    key === 'ArrowRight'
      ? Math.min(TABS.length - 1, idx + 1)
      : Math.max(0, idx - 1);
  if (next === idx) return null;
  const nextTab = TABS[next];
  // 'details' navigates to the bare id, which the router redirects to
  // /runs/:id/details (the canonical default-tab URL).
  return `/runs/${id}/${nextTab === 'details' ? '' : nextTab}`;
}

/**
 * Registers the app-wide keyboard shortcuts for the lifetime of the calling
 * component.
 */
export function useGlobalShortcuts() {
  const navigate = useNavigate();
  const location = useLocation();

  // Re-runs (removing and re-adding the single document keydown listener) on
  // every pathname change so the handler closure always sees the current
  // route; cleanup on unmount removes the last listener.
  useEffect(() => {
    // Timestamp of the last bare "g" press, held in the effect closure (not
    // state -- it should never cause a render). Reset whenever the effect
    // re-runs, which harmlessly drops a pending "g" across a navigation.
    let lastG = 0;

    function onKeyDown(e: KeyboardEvent) {
      if (isTextEditingTarget(e.target)) return;
      // Leave modifier combos (browser/OS shortcuts) alone.
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const now = Date.now();
      // Two-key "g n" sequence (Vim-style).
      if (e.key === 'g') {
        lastG = now;
        return;
      }
      // The prefix is only honored within 800ms, and any non-"g" key
      // consumes it so a stale "g" can't pair with a much later "n".
      const wasG = now - lastG < 800;
      lastG = 0;

      if (wasG && e.key === 'n') {
        e.preventDefault();
        void navigate('/');
        return;
      }

      // Tab nav while on a run page.
      const path = nextTabPath(location.pathname, e.key);
      if (path) {
        e.preventDefault();
        void navigate(path);
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [navigate, location.pathname]);
}
