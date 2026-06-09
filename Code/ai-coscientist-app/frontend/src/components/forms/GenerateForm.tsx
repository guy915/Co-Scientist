import { AlertCircle, CheckCircle2, Upload, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { getConfig, getSystemStatus, type SystemStatusResponse } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible } from "@/components/ui/collapsible";
import { IconRenderer } from "@/components/ui/IconRenderer";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useGenerationContext } from "@/context/GenerationContext";
import { useDomainText } from "@/hooks/useDomainText";
import type { GenerateFormData } from "@/types/forms";
import type { GenerationState } from "@/types/workflow";
import { saveLastRunState } from "@/utils/statePersistence";

interface GenerateFormProps {
  onSubmit: (data: GenerateFormData) => void;
  isGenerating?: boolean;
}

export function GenerateForm({ onSubmit, isGenerating = false }: GenerateFormProps) {
  const { dispatch } = useGenerationContext();
  const { t, item, goal, action, config } = useDomainText();
  const appIcon = config.appIcon || "Sparkles";
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [researchGoal, setResearchGoal] = useState("");
  const [modelName, setModelName] = useState("gemini/gemini-2.5-flash");
  const [maxIterations, setMaxIterations] = useState(1);
  const [initialHypothesesCount, setInitialHypothesesCount] = useState(3);
  const [evolutionMaxCount, setEvolutionMaxCount] = useState(2);
  const [enableStreaming, setEnableStreaming] = useState(true);
  const [enableLiteratureReviewNode, setEnableLiteratureReviewNode] = useState<boolean | undefined>(
    undefined
  );
  const [systemStatus, setSystemStatus] = useState<SystemStatusResponse | null>(null);
  const [errors, setErrors] = useState<{ [key: string]: string }>({});

  // fetch config defaults and system status from server on mount
  useEffect(() => {
    // fetch config
    getConfig()
      .then((config) => {
        setMaxIterations(config.max_iterations);
        setInitialHypothesesCount(3);
        setEvolutionMaxCount(config.evolution_max_count);
      })
      .catch((error) => {
        console.error("failed to fetch config:", error);
      });

    // fetch system status
    getSystemStatus()
      .then((status) => {
        setSystemStatus(status);
        // default to true if literature review is available, undefined for auto-detect
        if (status.literature_review_available) {
          setEnableLiteratureReviewNode(true);
        }
      })
      .catch((error) => {
        console.error("failed to fetch system status:", error);
      });
  }, []);

  const validateForm = (): boolean => {
    const newErrors: { [key: string]: string } = {};

    if (!researchGoal.trim()) {
      newErrors.research_goal = `${goal.Singular} is required`;
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    onSubmit({
      research_goal: researchGoal,
      model_name: modelName,
      max_iterations: maxIterations,
      initial_hypotheses_count: initialHypothesesCount,
      evolution_max_count: evolutionMaxCount,
      enable_streaming: enableStreaming,
      enable_literature_review_node: enableLiteratureReviewNode,
    });
  };

  const handleLoadFromFile = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const text = event.target?.result as string;
        const state = JSON.parse(text) as GenerationState;

        // Validate the loaded state has required fields
        if (!state.status || !state.hypotheses || !Array.isArray(state.hypotheses)) {
          alert("Invalid state file: missing required fields");
          return;
        }

        // Save to sessionStorage so it persists
        saveLastRunState(state);

        // Restore the state
        dispatch({ type: "RESTORE_STATE", payload: state });

        console.log("[GenerateForm] Loaded state from file:", state.taskId || "no-task-id");
        console.log(
          `Successfully loaded run state from file${state.taskId ? ` (Task: ${state.taskId})` : ""}`
        );
      } catch (error) {
        console.error("[GenerateForm] Error loading file:", error);
        alert("Failed to load state file. Please ensure it is a valid JSON file.");
      }
    };

    reader.onerror = () => {
      alert("Error reading file");
    };

    reader.readAsText(file);

    // Reset the input so the same file can be selected again
    e.target.value = "";
  };

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <IconRenderer
            icon={appIcon}
            className="w-5 h-5"
            style={{ color: "var(--color-th-primary)" }}
          />
          {t("page_title")}
        </CardTitle>
        <CardDescription className="space-y-2">
          <p>{t("form_description")}</p>
          {/* Conditional attribution text */}
          {config.ui?.attribution_text === undefined ? (
            // Default hardcoded attribution text
            <p className="">
              Based on{" "}
              <a
                target="_blank"
                className="underline"
                style={{ color: "var(--color-th-link)" }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--color-th-link-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--color-th-link)")}
                rel="noopener noreferrer"
                href="https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/"
              >
                AI Co-Scientist
              </a>
              , a multi-agent AI system developed by Google Research{" "}
              <a
                href="https://arxiv.org/abs/2502.18864"
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
                style={{ color: "var(--color-th-link)" }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--color-th-link-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--color-th-link)")}
              >
                (paper)
              </a>
              .
            </p>
          ) : config.ui?.attribution_text !== null ? (
            // Custom attribution text from domain config
            <p className="">{config.ui.attribution_text}</p>
          ) : null}
          {/* If attribution_text is null, nothing is rendered */}

          {/* system status badges */}
          {systemStatus && (
            <div className="flex flex-wrap gap-2 pt-2">
              <Badge
                variant={systemStatus.mcp_available ? "default" : "secondary"}
                className="text-xs"
              >
                {systemStatus.mcp_available ? (
                  <>
                    <CheckCircle2 className="w-3 h-3 mr-1" />
                    MCP Server
                  </>
                ) : (
                  <>
                    <XCircle className="w-3 h-3 mr-1" />
                    MCP Server
                  </>
                )}
              </Badge>
              {/* Conditionally show PubMed badge based on domain config */}
              {(config.showPubmedBadge ?? true) && (
                <Badge
                  variant={systemStatus.pubmed_available ? "default" : "secondary"}
                  className="text-xs"
                >
                  {systemStatus.pubmed_available ? (
                    <>
                      <CheckCircle2 className="w-3 h-3 mr-1" />
                      PubMed
                    </>
                  ) : (
                    <>
                      <XCircle className="w-3 h-3 mr-1" />
                      PubMed
                    </>
                  )}
                </Badge>
              )}
              <Badge
                variant={systemStatus.literature_review_available ? "default" : "outline"}
                className="text-xs"
              >
                {systemStatus.literature_review_available ? (
                  <>
                    <CheckCircle2 className="w-3 h-3 mr-1" />
                    Literature Review
                  </>
                ) : (
                  <>
                    <AlertCircle className="w-3 h-3 mr-1" />
                    Literature Review
                  </>
                )}
              </Badge>
            </div>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Research Goal Input */}
          <div className="space-y-2">
            <Label htmlFor="research-goal">
              {goal.Singular} <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="research-goal"
              placeholder={t("input_placeholder_example")}
              value={researchGoal}
              onChange={(e) => setResearchGoal(e.target.value)}
              rows={6}
              disabled={isGenerating}
              className={errors.research_goal ? "border-destructive" : ""}
            />
            <p className="text-sm text-muted-foreground">{t("input_description")}</p>
            <ul className="text-sm text-muted-foreground list-disc list-inside space-y-1 ml-2">
              <li>
                <strong>{t("input_preference_label")}:</strong> {t("input_preference_example")}
              </li>
              <li>
                <strong>{t("input_attributes_label")}:</strong> {t("input_attributes_example")}
              </li>
              <li>
                <strong>{t("input_constraints_label")}:</strong> {t("input_constraints_example")}
              </li>
              <li>
                <strong>{t("input_context_label")}:</strong> {t("input_context_example")}
              </li>
            </ul>
            <p className="text-xs text-muted-foreground italic mt-2">{t("input_help_text")}</p>
            {errors.research_goal && (
              <p className="text-sm text-destructive">{errors.research_goal}</p>
            )}
          </div>

          {/* Advanced Configuration */}
          <Collapsible trigger="Advanced Configuration">
            <div className="space-y-4">
              {/* Grid for all inputs */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-2xl">
                {/* Model Selection */}
                <div className="space-y-2">
                  <Label htmlFor="model-name">Model</Label>
                  <select
                    id="model-name"
                    value={modelName}
                    onChange={(e) => setModelName(e.target.value)}
                    disabled={isGenerating}
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <option value="gemini/gemini-2.5-flash">Gemini 2.5 Flash</option>
                    <option value="gemini/gemini-2.5-flash-lite">Gemini 2.5 Flash Lite</option>
                    <option value="gemini/gemini-2.5-pro">Gemini 2.5 Pro</option>
                    <option value="gemini/gemini-2.0-flash">Gemini 2.0 Flash</option>
                    <option value="gemini/gemini-2.0-flash-lite">Gemini 2.0 Flash Lite</option>
                    <option value="gemini/gemini-3-flash-preview">Gemini 3 Flash Preview</option>
                    <option value="gemini/gemini-3-pro-preview">Gemini 3 Pro Preview</option>
                  </select>
                </div>

                {/* Max Iterations */}
                <div className="space-y-2">
                  <Label htmlFor="max-iterations">
                    Max Iterations
                    <span className="ml-2 text-xs text-muted-foreground font-normal">(0-25)</span>
                  </Label>
                  <Input
                    id="max-iterations"
                    type="number"
                    min="0"
                    max="25"
                    value={maxIterations}
                    onChange={(e) => setMaxIterations(Number(e.target.value))}
                    disabled={isGenerating}
                  />
                </div>

                {/* Initial Hypotheses Count */}
                <div className="space-y-2">
                  <Label htmlFor="initial-hypotheses-count">
                    Initial {item.Plural} Count
                    <span className="ml-2 text-xs text-muted-foreground font-normal">(3-100)</span>
                  </Label>
                  <Input
                    id="initial-hypotheses-count"
                    type="number"
                    min="3"
                    max="100"
                    value={initialHypothesesCount}
                    onChange={(e) => setInitialHypothesesCount(Number(e.target.value))}
                    disabled={isGenerating}
                  />
                </div>

                {/* Evolution Max Count */}
                <div className="space-y-2">
                  <Label htmlFor="evolution-max-count">
                    Evolution Max Count
                    <span className="ml-2 text-xs text-muted-foreground font-normal">(1-50)</span>
                  </Label>
                  <Input
                    id="evolution-top-k"
                    type="number"
                    min="1"
                    max="50"
                    value={evolutionMaxCount}
                    onChange={(e) => setEvolutionMaxCount(Number(e.target.value))}
                    disabled={isGenerating}
                    className={errors.evolution_max_count ? "border-destructive" : ""}
                  />
                  {errors.evolution_max_count && (
                    <p className="text-sm text-destructive">{errors.evolution_max_count}</p>
                  )}
                </div>
              </div>

              {/* Literature Review Toggle */}
              <div className="flex items-start space-x-3 pt-4 border-t">
                <Checkbox
                  id="enable-literature-review-node"
                  checked={enableLiteratureReviewNode === true}
                  onCheckedChange={(checked) =>
                    setEnableLiteratureReviewNode(checked === true ? true : false)
                  }
                  disabled={isGenerating || !systemStatus?.mcp_available}
                />
                <div className="flex-1">
                  <Label
                    htmlFor="enable-literature-review-node"
                    className="font-medium cursor-pointer"
                  >
                    Include Literature Review
                  </Label>
                  <p className="text-sm text-muted-foreground mt-1">
                    {systemStatus?.mcp_available
                      ? `Uses literature review tools to enhance ${item.singular} ${action.noun} with research context`
                      : "Literature review tools unavailable - mcp server not detected"}
                  </p>
                  {systemStatus?.mcp_available && (
                    <p className="text-xs text-muted-foreground mt-1">
                      mcp server: {systemStatus.mcp_server_url}
                    </p>
                  )}
                </div>
              </div>

              {/* Real-time Updates Toggle */}
              <div className="flex items-start space-x-3 pt-4">
                <input
                  type="checkbox"
                  id="enable-streaming"
                  checked={enableStreaming}
                  onChange={(e) => setEnableStreaming(e.target.checked)}
                  disabled={isGenerating}
                  className="mt-1 h-4 w-4 rounded border-th-border text-primary focus:ring-primary"
                />
                <div className="flex-1">
                  <Label htmlFor="enable-streaming" className="font-medium cursor-pointer">
                    Enable Real-time Updates
                  </Label>
                  <p className="text-sm text-muted-foreground mt-1">
                    Show progress as {item.plural} are {action.past} (streaming). Disable to wait
                    for results, with no intermediary updates.
                  </p>
                </div>
              </div>

              {/* Load from File */}
              <div className="pt-4 border-t">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleLoadFromFile}
                  disabled={isGenerating}
                  className="w-full"
                >
                  <Upload className="w-4 h-4 mr-2" />
                  Load From File
                </Button>
                <p className="text-xs text-muted-foreground mt-2">
                  Load a previously downloaded run JSON file to restore state.
                </p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json"
                  onChange={handleFileChange}
                  className="hidden"
                />
              </div>
            </div>
          </Collapsible>

          {/* Submit Button */}
          <Button type="submit" size="lg" disabled={isGenerating} className="w-full cursor-pointer">
            {isGenerating ? (
              <>
                <span className="animate-spin mr-2">⟳</span>
                {action.Gerund}...
              </>
            ) : (
              <>
                <IconRenderer icon={appIcon} className="w-4 h-4 mr-2" />
                {t("submit_button")}
              </>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
