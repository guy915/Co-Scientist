import {type ReactElement} from 'react';
import {Navigate, Route, Routes} from 'react-router-dom';
import {ErrorBoundary} from '@/components/error_boundary';
import {NoIndex} from '@/public/no_index';
import {NotFoundPage} from '@/public/not_found_page';
import {useGlobalShortcuts} from './hooks/use_global_shortcuts';
import {RunHistoryProvider} from './hooks/run_history_context';
import {Layout} from './layout';
import {ChatWorkspace} from './pages/chat_workspace';
import {ProposalsPage} from './pages/proposals_page';
import {RunDetail} from './pages/run_detail';
import {SharedGoalReportPage} from './pages/shared_goal_report';
import {ResearcherAccessPage} from './pages/researcher_access';
import {AudienceProvider} from './audience_context';
import {ThemeProvider} from './theme_context';

// Render-nothing bridge: useGlobalShortcuts needs react-router hooks, so it
// must run inside the router but can't live in WorkbenchApp itself (the
// BrowserRouter is mounted above this component, in main.tsx).
function ShortcutsBridge() {
  useGlobalShortcuts();
  return null;
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
      {/* Legacy entry points from the retired public surface; both now
          land on the chat workspace, which owns run creation. */}
      <Route path="/runs" element={<Navigate to="/" replace />} />
      <Route path="/runs/new" element={<Navigate to="/" replace />} />
      <Route
        path="/access"
        element={page('Researcher access', <ResearcherAccessPage />)}
      />
      <Route path="/proposals" element={page('Proposals', <ProposalsPage />)} />
      {/* The page was published as /recommendations before it became the
          proposals graph; keep the old path working. */}
      <Route
        path="/recommendations"
        element={<Navigate to="/proposals" replace />}
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
        <AudienceProvider>
          <RunHistoryProvider>
            <Layout>
              <ShortcutsBridge />
              <WorkbenchRoutes />
            </Layout>
          </RunHistoryProvider>
        </AudienceProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
