import {Route, Routes} from 'react-router-dom';
import {ErrorBoundary} from '@/components/error_boundary';
import {DemoPage} from '@/public/demo_page';
import {LandingPage} from '@/public/landing_page';
import {NoIndex} from '@/public/no_index';
import {NotFoundPage} from '@/public/not_found_page';
import {useGlobalShortcuts} from './hooks/use_global_shortcuts';
import {Layout} from './layout';
import {Dashboard} from './pages/dashboard';
import {NewRun} from './pages/new_run';
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
            <Route path="/" element={<LandingPage />} />
            <Route path="/demos/:slug" element={<DemoPage />} />
            <Route
              path="/runs"
              element={
                <>
                  <NoIndex title="Research runs" />
                  <Dashboard />
                </>
              }
            />
            <Route
              path="/runs/new"
              element={
                <>
                  <NoIndex title="New research run" />
                  <NewRun />
                </>
              }
            />
            <Route
              path="/runs/:id"
              element={
                <>
                  <NoIndex title="Research run" />
                  <RunDetail />
                </>
              }
            />
            <Route
              path="/runs/:id/:tab"
              element={
                <>
                  <NoIndex title="Research run" />
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
