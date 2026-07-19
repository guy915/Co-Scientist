// Application entry point: mounts the workbench SPA into the #root element of
// index.html, under StrictMode and a BrowserRouter (path-based routing; route
// definitions live in workbench_app.tsx).
import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import './index.css'; // Tailwind layers + --color-th-* theme bridge variables
import './styles/index.css'; // app-specific global styles
import {
  installUiErrorLogging,
  installUiInteractionLogging,
} from './lib/ui_logging';
import {WorkbenchApp} from './workbench/workbench_app';

// Installed before the first render so a crash during mount is persisted
// to the app-wide log rather than lost to the browser console. Clicks and
// form submissions are captured the same way, so user actions line up
// with the backend records they trigger.
installUiErrorLogging();
installUiInteractionLogging();

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
