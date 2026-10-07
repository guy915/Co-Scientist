import {lazy, type ReactElement, Suspense} from 'react';
import {Navigate, Route, Routes} from 'react-router-dom';
import {ErrorBoundary} from '@/components/error_boundary';
import {NoIndex} from '@/public/page';
import {NotFoundPage} from '@/public/page';
import {ChatHistoryProvider} from './hooks/history_context';
import {RunHistoryProvider} from './hooks/history_context';
import {SystemStatusProvider} from './hooks/system_status_context';
import {Layout} from './layout';
import {ChatWorkspace} from './pages/chat_workspace';
import {ExampleChat} from './pages/example_chat';
import {ThemeProvider} from './theme_context';

const RunDetail = lazy(() =>
  import('./pages/run_detail').then(module => ({default: module.RunDetail})),
);

function PageLoading() {
  return (
    <div className="grid h-full min-h-0 place-items-center p-6 text-sm text-cosci-muted">
      <p role="status">Loading page…</p>
    </div>
  );
}

function page(title: string, element: ReactElement) {
  return (
    <>
      <NoIndex title={title} />
      {element}
    </>
  );
}

function WorkbenchRoutes() {
  return (
    <Routes>
      <Route path="/" element={page('Workspace', <ChatWorkspace />)} />
      <Route path="/chats/:id" element={page('Workspace', <ChatWorkspace />)} />
      <Route
        path="/examples/:id"
        element={page('Example chat', <ExampleChat />)}
      />
      <Route path="/runs" element={<Navigate to="/" replace />} />
      <Route path="/runs/new" element={<Navigate to="/" replace />} />
      {/* One required-param route makes tab changes reuse RunDetail instead of refetching and blanking the header. */}
      <Route path="/runs/:id" element={<Navigate to="details" replace />} />
      <Route
        path="/runs/:id/:tab"
        element={page('Goal Report', <RunDetail />)}
      />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

export function WorkbenchApp() {
  // Keep the boundary outside theme/layout so their crashes are caught while
  // the shell persists across route changes.
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <SystemStatusProvider>
          <RunHistoryProvider>
            <ChatHistoryProvider>
              <Layout>
                <Suspense fallback={<PageLoading />}>
                  <WorkbenchRoutes />
                </Suspense>
              </Layout>
            </ChatHistoryProvider>
          </RunHistoryProvider>
        </SystemStatusProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
