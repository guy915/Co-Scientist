import {subscribeDataErasure} from '@/shared/lib/data_erasure_sync';
import {lazy, type ReactElement, Suspense, useEffect} from 'react';
import {Navigate, Route, Routes} from 'react-router-dom';
import {ErrorBoundary} from '@/shared/ui/error_boundary';
import {NoIndex} from './not_found_page';
import {NotFoundPage} from './not_found_page';
import {ChatHistoryProvider} from '@/shared/hooks/history_context';
import {RunHistoryProvider} from '@/shared/hooks/history_context';
import {SystemStatusProvider} from '@/shared/hooks/system_status_context';
import {Layout} from './layout';
import {ChatWorkspace} from '@/features/chat/chat_workspace';
import {ExampleChat} from '@/features/chat/example_chat';
import {ThemeProvider} from '@/shared/hooks/theme_context';
import {PageStatus} from '@/shared/ui';

const RunDetail = lazy(() =>
  import('@/features/report/run_detail').then(module => ({
    default: module.RunDetail,
  })),
);

const LegalPage = lazy(() =>
  import('@/features/legal/legal_page').then(module => ({
    default: module.LegalPage,
  })),
);

function PageLoading() {
  return <PageStatus>Loading page…</PageStatus>;
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
      <Route path="/privacy" element={<LegalPage kind="privacy" />} />
      <Route path="/terms" element={<LegalPage kind="terms" />} />
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
  useEffect(() => subscribeDataErasure(() => window.location.assign('/')), []);
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
