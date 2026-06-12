/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

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
