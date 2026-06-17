import {Route, Routes} from 'react-router-dom';
import {ErrorBoundary} from '@/components/ErrorBoundary';
import {LocaleProvider, useT} from '@/i18n';
import {DemoPage} from '@/public/DemoPage';
import {LandingPage} from '@/public/LandingPage';
import {NoIndex} from '@/public/NoIndex';
import {NotFoundPage} from '@/public/NotFoundPage';
import {useGlobalShortcuts} from './hooks/useGlobalShortcuts';
import {Layout} from './Layout';
import {Dashboard} from './pages/Dashboard';
import {NewRun} from './pages/NewRun';
import {RunDetail} from './pages/RunDetail';
import {ThemeProvider} from './ThemeContext';

function ShortcutsBridge() {
  useGlobalShortcuts();
  return null;
}

function AppRoutes() {
  const t = useT();
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/demos/:slug" element={<DemoPage />} />
      <Route
        path="/runs"
        element={
          <>
            <NoIndex title={t('runDetail.title.runs')} />
            <Dashboard />
          </>
        }
      />
      <Route
        path="/runs/new"
        element={
          <>
            <NoIndex title={t('runDetail.title.new')} />
            <NewRun />
          </>
        }
      />
      <Route
        path="/runs/:id"
        element={
          <>
            <NoIndex title={t('runDetail.title.run')} />
            <RunDetail />
          </>
        }
      />
      <Route
        path="/runs/:id/:tab"
        element={
          <>
            <NoIndex title={t('runDetail.title.run')} />
            <RunDetail />
          </>
        }
      />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

/**
 * Root workbench component wiring routing, theming, locale, and error handling.
 */
export function WorkbenchApp() {
  return (
    <ErrorBoundary>
      <LocaleProvider>
        <ThemeProvider>
          <Layout>
            <ShortcutsBridge />
            <AppRoutes />
          </Layout>
        </ThemeProvider>
      </LocaleProvider>
    </ErrorBoundary>
  );
}
