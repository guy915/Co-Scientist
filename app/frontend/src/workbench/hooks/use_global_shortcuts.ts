import {useEffect} from 'react';
import {useLocation, useNavigate} from 'react-router-dom';

/**
 * Global keyboard shortcuts:
 *   g d  -> /runs
 *   g n  -> /
 *   ←/→  -> cycle tabs on /runs/:id
 * Inputs and textareas are ignored so typing doesn't trigger the bindings.
 */
const TABS = ['overview', 'ideas', 'evidence', 'tournament', 'report'] as const;

function isTextEditingTarget(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
}

/**
 * Registers the app-wide keyboard shortcuts (g-d, g-n, and arrow-key tab
 * navigation) for the lifetime of the calling component.
 */
export function useGlobalShortcuts() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    let lastG = 0;

    function onKeyDown(e: KeyboardEvent) {
      if (isTextEditingTarget(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const now = Date.now();
      // Two-key "g d" / "g n" sequence (Vim-style).
      if (e.key === 'g') {
        lastG = now;
        return;
      }
      const wasG = now - lastG < 800;
      lastG = 0;

      if (wasG && e.key === 'd') {
        e.preventDefault();
        void navigate('/runs');
        return;
      }
      if (wasG && e.key === 'n') {
        e.preventDefault();
        void navigate('/');
        return;
      }

      // Tab nav while on a run page.
      const m = location.pathname.match(/^\/runs\/([^/]+)(?:\/(.+))?$/);
      if (m && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
        const id = m[1];
        if (id === 'new') return;
        const current = (
          m[2] && (TABS as readonly string[]).includes(m[2]) ? m[2] : 'overview'
        ) as (typeof TABS)[number];
        const idx = TABS.indexOf(current);
        const next =
          e.key === 'ArrowRight'
            ? Math.min(TABS.length - 1, idx + 1)
            : Math.max(0, idx - 1);
        if (next !== idx) {
          e.preventDefault();
          const nextTab = TABS[next];
          void navigate(`/runs/${id}/${nextTab === 'overview' ? '' : nextTab}`);
        }
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [navigate, location.pathname]);
}
