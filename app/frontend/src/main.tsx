import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import './index.css';
import './styles/tokens.css';
import './styles/shell_surface.css';
import './styles/home_surface.css';
import './styles/home_landing.css';
import './styles/tooltips.css';
import {
  installUiErrorLogging,
  installUiInteractionLogging,
} from './lib/ui_logging';
import {WorkbenchApp} from './workbench/workbench_app';

// Install error capture before mounting so first-render crashes survive outside
// the browser console.
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
