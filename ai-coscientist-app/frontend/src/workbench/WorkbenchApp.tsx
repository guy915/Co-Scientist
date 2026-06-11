import { Route, Routes } from "react-router-dom";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { DemoPage } from "@/public/DemoPage";
import { LandingPage } from "@/public/LandingPage";
import { NoIndex } from "@/public/NoIndex";
import { NotFoundPage } from "@/public/NotFoundPage";
import { useGlobalShortcuts } from "./hooks/useGlobalShortcuts";
import { Layout } from "./Layout";
import { Dashboard } from "./pages/Dashboard";
import { NewRun } from "./pages/NewRun";
import { RunDetail } from "./pages/RunDetail";
import { ThemeProvider } from "./ThemeContext";

function ShortcutsBridge() {
  useGlobalShortcuts();
  return null;
}

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
