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
import {ThemeProvider} from './theme_context';

const RunDetail = lazy(() =>
  import('./pages/run_detail').then(module => ({default: module.RunDetail})),
);
const SharedGoalReportPage = lazy(() =>
  import('./pages/shared_goal_report').then(module => ({
    default: module.SharedGoalReportPage,
  })),
);
const ResearcherAccessPage = lazy(() =>
  import('./pages/researcher_access').then(module => ({
    default: module.ResearcherAccessPage,
  })),
);

/** Keeps the existing shell visible while a routed page is downloaded. */
function PageLoading() {
  return (
    <div className="grid h-full min-h-0 place-items-center p-6 text-sm text-cosci-muted">
      <p role="status">Loading page…</p>
    </div>
  );
}

// Every routed page mounts with a NoIndex tag; this pairs them once.
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
      {/* "/" is the chat workspace: the session home where new runs are
          drafted and started. */}
      <Route path="/" element={page('Workspace', <ChatWorkspace />)} />
      {/* A chat reopened from the rail. Same page as "/", which reads :id
          and rehydrates the durable interview behind the conversation. */}
      <Route path="/chats/:id" element={page('Workspace', <ChatWorkspace />)} />
      {/* Legacy entry points from the retired public surface; both now
          land on the chat workspace, which owns run creation. */}
      <Route path="/runs" element={<Navigate to="/" replace />} />
      <Route path="/runs/new" element={<Navigate to="/" replace />} />
      <Route
        path="/access"
        element={page('Researcher access', <ResearcherAccessPage />)}
      />
      <Route
        path="/shared/:token"
        element={page('Shared Goal Report', <SharedGoalReportPage />)}
      />
      {/* Redirect the bare id to the default tab so every tab shares one
          required-param route: switching tabs is a param change, not a
          remount (a remount refetches and blanks the shell header). */}
      <Route path="/runs/:id" element={<Navigate to="details" replace />} />
      {/* Run detail with its active tab in the URL (details, learning,
          overview, ideas); RunDetail reads :id and :tab via useParams. */}
      <Route
        path="/runs/:id/:tab"
        element={page('Goal Report', <RunDetail />)}
      />
      {/* Catch-all 404 for anything outside the routes above. */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

/**
 * Root workbench component wiring routing, theming, and the error boundary.
 */
export function WorkbenchApp() {
  // Provider nesting: ErrorBoundary outermost so theme/layout crashes are
  // caught too; Layout wraps the Routes so the shell (rail, header) persists
  // across navigations and only the routed page content swaps.
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
