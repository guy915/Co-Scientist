import { Download } from "lucide-react";
import { useEffect } from "react";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { GenerateForm } from "@/components/forms/GenerateForm";
import { HypothesisList } from "@/components/hypothesis/HypothesisList";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { AgentActivitySection } from "@/components/workflow/AgentActivitySection";
import { GeneratingHeader } from "@/components/workflow/GeneratingHeader";
import { HypothesisFocusBanner } from "@/components/workflow/HypothesisFocusBanner";
import { DomainProvider } from "@/context/DomainContext";
import { GenerationProvider } from "@/context/GenerationContext";
import { HypothesisFocusProvider, useHypothesisFocus } from "@/context/HypothesisFocusContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { useHypothesisGeneration } from "@/hooks/useHypothesisGeneration";
import type { GenerateFormData } from "@/types/forms";
import { exportToJSON } from "@/utils/exportUtils";

function AppContent() {
  const { state, startGeneration, cancelGeneration, resetGeneration } = useHypothesisGeneration();
  const { unpin } = useHypothesisFocus();

  // Clear pinned hypothesis when a new generation starts
  useEffect(() => {
    if (state.status === "generating") {
      unpin();
    }
  }, [state.status]);

  // Log final state size when a run completes
  useEffect(() => {
    if (state.status === "completed") {
      const json = JSON.stringify(state);
      const sizeKb = json.length / 1024;
      console.log("[Generation] Completed run; final state size:", `${sizeKb.toFixed(2)} KB`);
    }
  }, [state]);

  const handleGenerate = (data: GenerateFormData) => {
    console.log("Starting generation with:", data);
    startGeneration({
      research_goal: data.research_goal,
      model_name: data.model_name,
      max_iterations: data.max_iterations,
      initial_hypotheses_count: data.initial_hypotheses_count,
      evolution_max_count: data.evolution_max_count,
      enable_streaming: data.enable_streaming,
      enable_literature_review_node: data.enable_literature_review_node,
    });
  };

  const handleCancel = () => {
    console.log("Canceling generation");
    cancelGeneration();
  };

  const handleReset = () => {
    console.log("Resetting for new generation");
    resetGeneration();
  };

  const isGenerating = state.status === "generating" || state.status === "cancelling";
  const isCompleted = state.status === "completed";
  const hasError = state.status === "error";
  const isCancelling = state.status === "cancelling";

  return (
    <div className="min-h-screen" style={{ backgroundColor: "var(--color-th-bg)" }}>
      <Header />
      <HypothesisFocusBanner />

      <main className="container mx-auto px-4 py-8">
        <div className="max-w-6xl mx-auto space-y-6">
          {/* Input Form (shown when idle, completed, or cancelled) */}
          {(state.status === "idle" || isCompleted || state.status === "cancelled") && (
            <GenerateForm onSubmit={handleGenerate} isGenerating={isGenerating} />
          )}

          {/* Generating Header (shown during generation or cancelling) */}
          {isGenerating && (
            <GeneratingHeader
              researchGoal={state.researchGoal}
              progress={state.progress}
              progressMessage={state.progressMessage}
              onCancel={handleCancel}
              isCancelling={isCancelling}
            />
          )}

          {/* Error Display */}
          {hasError && (
            <div
              className="p-4 rounded-lg border"
              style={{
                backgroundColor: "color-mix(in srgb, var(--color-th-destructive) 10%, transparent)",
                borderColor: "var(--color-th-destructive)",
              }}
            >
              <h3 className="font-semibold mb-2" style={{ color: "var(--color-th-destructive)" }}>
                Error
              </h3>
              <p className="text-sm" style={{ color: "var(--color-th-destructive)" }}>
                {state.error}
              </p>
              <button
                onClick={handleReset}
                className="mt-3 text-sm hover:underline"
                style={{ color: "var(--color-th-destructive)" }}
              >
                Try Again
              </button>
            </div>
          )}

          {/* Agent Activity (shown when there are agent outputs) */}
          {state.agentOutputs.length > 0 && (
            <AgentActivitySection agentOutputs={state.agentOutputs} />
          )}

          {/* Results (shown when completed) */}
          {isCompleted && state.hypotheses.length > 0 && (
            <>
              <HypothesisList
                hypotheses={state.hypotheses}
                researchGoal={state.researchGoal}
                executionTime={state.executionTime}
                metrics={state.metrics}
              />

              {/* Export full run state (for debugging / future rehydration) */}
              <div className="mt-4">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    const data = {
                      ...state,
                      exported_at: new Date().toISOString(),
                    };
                    const filename = `hypothesis-run-full-${state.taskId || "no-task"}.json`;
                    exportToJSON(data, filename);
                  }}
                >
                  <Download className="w-4 h-4 mr-1" />
                  Download Full Results
                </Button>
              </div>

              {/* New Generation Button */}
              {/* <div className="flex justify-center">
                <button
                  onClick={handleReset}
                  className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  Generate New Hypotheses
                </button>
              </div> */}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <DomainProvider>
        <ThemeProvider>
          <GenerationProvider>
            <HypothesisFocusProvider>
              <AppContent />
            </HypothesisFocusProvider>
          </GenerationProvider>
        </ThemeProvider>
      </DomainProvider>
    </ErrorBoundary>
  );
}

export default App;
