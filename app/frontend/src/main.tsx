import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import './index.css';
import './styles/tokens.css';
import './styles/shell_surface.css';
import './styles/home_surface.css';
import './styles/home_landing.css';
import './styles/tooltips.css';
import './shared/ui/motion.css';
import {
  installUiErrorLogging,
  installUiInteractionLogging,
} from '@/shared/lib/ui_logging';
import {WorkbenchApp} from './workbench/workbench_app';

// Install error capture before mounting so first-render crashes survive outside
// the browser console.
installUiErrorLogging();
installUiInteractionLogging();

// The SDK loads as its own chunk only when a DSN is built in, so the main
// bundle and builds without one are unchanged.
const sentryDsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
if (sentryDsn) {
  void import('@/shared/lib/error_tracking').then(({initErrorTracking}) =>
    initErrorTracking(sentryDsn),
  );
}

// A deploy deletes the old hashed chunks; reload once to fetch the new index.
// The timestamp guard stops a reload loop if the chunk is genuinely missing.
window.addEventListener('vite:preloadError', event => {
  const key = 'coscientist:chunk-reload-at';
  try {
    const last = Number(sessionStorage.getItem(key));
    if (Date.now() - last < 10_000) {
      return;
    }
    sessionStorage.setItem(key, String(Date.now()));
  } catch {
    return;
  }
  event.preventDefault();
  window.location.reload();
});

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Missing #root element in index.html.');
}

createRoot(rootElement).render(
  <StrictMode>
    <BrowserRouter>
      <WorkbenchApp />
    </BrowserRouter>
  </StrictMode>,
);
