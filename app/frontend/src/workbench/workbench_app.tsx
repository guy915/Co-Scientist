import {Navigate, Route, Routes} from 'react-router-dom';
import {ErrorBoundary} from '@/components/error_boundary';
import {NoIndex} from '@/public/no_index';
import {NotFoundPage} from '@/public/not_found_page';
import {useGlobalShortcuts} from './hooks/use_global_shortcuts';
import {Layout} from './layout';
import {ChatWorkspace} from './pages/chat_workspace';
import {RunDetail} from './pages/run_detail';
import {ThemeProvider} from './theme_context';

function ShortcutsBridge() {
  useGlobalShortcuts();
  return null;
}

/**
 * Root workbench component wiring routing, theming, and the error boundary.
 */
export function WorkbenchApp() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <Layout>
          <ShortcutsBridge />
          <Routes>
            <Route
              path="/"
              element={
                <>
                  <NoIndex title="Workspace" />
                  <ChatWorkspace />
                </>
              }
            />
            <Route path="/runs" element={<Navigate to="/" replace />} />
            <Route path="/runs/new" element={<Navigate to="/" replace />} />
            {/* Redirect the bare id to the default tab so every tab shares one
                required-param route. Switching tabs is then a param change, not
                a remount — otherwise RunDetail refetches and its header-title
                effect flaps, blanking the shell header. */}
            <Route
              path="/runs/:id"
              element={<Navigate to="details" replace />}
            />
            <Route
              path="/runs/:id/:tab"
              element={
                <>
                  <NoIndex title="Goal Report" />
                  <RunDetail />
                </>
              }
            />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Layout>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
