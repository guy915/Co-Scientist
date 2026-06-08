import { useCallback, useRef } from "react";
import { useGenerationContext } from "@/context/GenerationContext";
import {
  startGeneration as apiStartGeneration,
  generateHypotheses as apiGenerateHypotheses,
  createStreamingURL,
  cancelGeneration as apiCancelGeneration,
} from "@/api/client";
import type { GenerateRequest } from "@/types/workflow";
import type { AgentOutput } from "@/types/agents";
import { normalizeHypotheses } from "@/utils/hypothesisUtils";
import { calculateOverallProgress } from "@/utils/progressCalculator";
import { useDomainText } from "@/hooks/useDomainText";

/**
 * Hook for managing hypothesis generation with SSE streaming
 */
export function useHypothesisGeneration() {
  const { state, dispatch } = useGenerationContext();
  const { t } = useDomainText();
  const eventSourceRef = useRef<EventSource | null>(null);
  const startTimeRef = useRef<number | null>(null);

  /**
   * Start hypothesis generation (streaming or non-streaming)
   */
  const startGeneration = useCallback(
    async (config: GenerateRequest) => {
      try {
        // Check if streaming is enabled (default: true)
        const useStreaming = config.enable_streaming !== false;

        if (!useStreaming) {
          // Non-streaming mode: Call /generate and wait for complete results
          dispatch({
            type: "START_GENERATION",
            payload: {
              taskId: "non-streaming",
              researchGoal: config.research_goal,
              maxIterations: config.max_iterations || 0,
            },
          });

          dispatch({
            type: "UPDATE_PROGRESS",
            payload: {
              progress: 50,
              message: t("loading_generating"),
            },
          });

          const result = await apiGenerateHypotheses(config);

          // Process complete results
          dispatch({
            type: "UPDATE_STATE",
            payload: {
              hypotheses: normalizeHypotheses(result.hypotheses || []),
              researchPlan: result.research_plan,
              metaReview: result.meta_review,
              tournamentMatchups: result.tournament_matchups,
              evolutionDetails: result.evolution_details,
              executionTime: result.execution_time,
              metrics: result.metrics,
            },
          });

          dispatch({
            type: "UPDATE_PROGRESS",
            payload: {
              progress: 100,
              message: t("loading_complete"),
            },
          });

          setTimeout(() => {
            dispatch({ type: "COMPLETE", payload: {} });
          }, 500);

          return;
        }

        // streaming mode: use sse
        // show loading state immediately before api call
        dispatch({
          type: "START_GENERATION",
          payload: {
            taskId: "pending", // temporary id while waiting for server
            researchGoal: config.research_goal,
            maxIterations: config.max_iterations || 0,
          },
        });

        // track start time for execution time calculation
        startTimeRef.current = Date.now();

        // step 1: post to start generation and get task_id
        const { task_id } = await apiStartGeneration(config);

        // update with actual task id
        dispatch({
          type: "UPDATE_STATE",
          payload: {
            taskId: task_id,
          },
        });

        // Step 2: Connect to SSE stream with task_id
        const url = createStreamingURL(task_id);
        const eventSource = new EventSource(url);
        eventSourceRef.current = eventSource;

        // Handle SSE events
        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            console.log("SSE Event:", data);

            // Handle different event types
            if (data.type === "start") {
              // Generation started
              dispatch({
                type: "UPDATE_PROGRESS",
                payload: {
                  progress: 5,
                  message: t("loading_start"),
                },
              });
            } else if (data.type === "update") {
              // Node completed, update state and progress
              if (data.state) {
                // Update state with new data, normalizing hypotheses
                dispatch({
                  type: "UPDATE_STATE",
                  payload: {
                    hypotheses: normalizeHypotheses(data.state.hypotheses || []),
                    researchPlan: data.state.research_plan,
                    metaReview: data.state.meta_review,
                    tournamentMatchups: data.state.tournament_matchups,
                    evolutionDetails: data.state.evolution_details,
                    similarityClusters: data.state.similarity_clusters,
                    currentIteration: data.state.ui_iteration ?? data.state.current_iteration,
                    metrics: data.state.metrics || {},
                  },
                });

                // Create AgentOutput for this node to display in AgentActivitySection
                const nodeNameMap: Record<string, string> = {
                  literature_review: "LiteratureReview",
                  supervisor: "Supervisor",
                  generate: "HypothesisGenerator",
                  reflection: "Reflection",
                  review: "HypothesisReflector",
                  rank: "HypothesisRanker",
                  ranking: "RankingJudge",
                  meta_review: "MetaReviewer",
                  evolve: "HypothesisEvolver",
                  proximity: "ProximityAnalyzer",
                };

                const agentName = nodeNameMap[data.node] || data.node;

                // Get iteration from server (ui_iteration is properly tracked)
                const uiIteration = data.state.ui_iteration ?? data.state.current_iteration ?? 0;

                // Determine phase based on ui_iteration
                let phase = "initial_generation";
                if (uiIteration === 0) {
                  phase = "initial_generation";
                } else {
                  phase = `iteration_${uiIteration}`;
                }

                // Extract relevant data for each agent type
                let parsedData: any = {};

                switch (data.node) {
                  case "supervisor":
                    parsedData = data.state.research_plan || {};
                    break;
                  case "literature_review":
                    parsedData = {
                      articles_with_reasoning: data.state.articles_with_reasoning || {},
                      literature_review_queries: data.state.literature_review_queries || [],
                      articles: data.state.articles || [],
                      context_enrichment_sources: data.state.context_enrichment_sources || [],
                    };
                    break;
                  case "generate":
                    parsedData = {
                      hypotheses: normalizeHypotheses(data.state.hypotheses || []),
                      debate_transcripts: data.state.debate_transcripts || [],
                    };
                    break;
                  case "reflection":
                    parsedData = {
                      hypotheses: data.state.hypotheses || [],
                    };
                    break;
                  case "review":
                    // Get ALL hypotheses with reviews
                    const hypothesesWithReviews = (data.state.hypotheses || []).filter(
                      (h: any) => h.reviews && h.reviews.length > 0
                    );

                    // Store for creating individual review cards later
                    parsedData = {
                      all_reviews: hypothesesWithReviews.map((hyp: any, hypIndex: number) => {
                        const latestReview = hyp.reviews[hyp.reviews.length - 1];
                        return {
                          hypothesis_text: hyp.text,
                          hypothesis_index: hypIndex,
                          overall_score: latestReview.overall_score,
                          review_summary:
                            latestReview.review_summary || latestReview.constructive_feedback,
                          scores: latestReview.scores || {},
                          constructive_feedback: latestReview.constructive_feedback,
                          detailed_feedback: latestReview.detailed_feedback || {
                            strengths: latestReview.strengths,
                            weaknesses: latestReview.weaknesses,
                          },
                        };
                      }),
                    };
                    break;
                  case "rank":
                    parsedData = {
                      ranked_hypotheses: (data.state.hypotheses || [])
                        .sort((a: any, b: any) => (b.score || 0) - (a.score || 0))
                        .map((h: any) => ({
                          text: h.text,
                          overall_score: (h.score || 0) / 10, // normalize 0-10 to 0-1
                        })),
                    };
                    break;
                  case "ranking":
                    // Get the latest tournament matchup
                    const matchups = data.state.tournament_matchups || [];
                    if (matchups.length > 0) {
                      const latestMatchup = matchups[matchups.length - 1];
                      parsedData = {
                        winner: latestMatchup.winner,
                        decision_summary: latestMatchup.reasoning || latestMatchup.decision_summary,
                        hypothesis_a: latestMatchup.hypothesis_a_text || latestMatchup.hypothesis_a,
                        hypothesis_b: latestMatchup.hypothesis_b_text || latestMatchup.hypothesis_b,
                        matchups: matchups, // keep full matchup list
                      };
                    } else {
                      parsedData = {
                        winner: "N/A",
                        decision_summary: "Ranking Tournament in progress",
                      };
                    }
                    break;
                  case "meta_review":
                    const metaReview = data.state.meta_review || {};
                    parsedData = {
                      summary: metaReview.summary,
                      common_strengths: metaReview.common_strengths,
                      common_weaknesses: metaReview.common_weaknesses,
                      strategic_recommendations: metaReview.strategic_recommendations || [],
                      emerging_themes: metaReview.emerging_themes || [],
                      areas_for_improvement: metaReview.areas_for_improvement || [],
                      diversity_assessment: metaReview.diversity_assessment,
                      top_performers_analysis: metaReview.top_performers_analysis,
                    };
                    break;
                  case "evolve":
                    // Get ALL evolution details, not just the latest
                    const evolutionDetails = data.state.evolution_details || [];
                    parsedData = {
                      evolved_count: evolutionDetails.length,
                      evolution_details: evolutionDetails,
                      refinement_summary:
                        evolutionDetails.length > 0
                          ? t("evolved_count", undefined, { count: evolutionDetails.length })
                          : t("loading_generating"),
                    };
                    break;
                  case "proximity":
                    parsedData = {
                      similarity_clusters: data.state.similarity_clusters || [],
                      hypotheses: data.state.hypotheses || [],
                      diversity_assessment: `${data.state.hypotheses?.length || 0} unique hypotheses after deduplication`,
                    };
                    break;
                  default:
                    parsedData = data.state;
                }

                // Only create agent output if parsedData is not null
                // (review case creates multiple outputs directly)
                if (parsedData !== null) {
                  const agentOutput: AgentOutput = {
                    name: agentName,
                    content: JSON.stringify(parsedData, null, 2),
                    parsed: parsedData,
                    timestamp: Date.now(),
                    phase,
                    iteration: uiIteration,
                  };

                  dispatch({ type: "ADD_AGENT_OUTPUT", payload: agentOutput });
                }

                // Calculate progress based on node, iteration, and maxIterations
                const maxIterations = state.maxIterations || 0;
                const currentIteration = uiIteration;

                const progressResult = calculateOverallProgress(
                  data.node,
                  currentIteration,
                  maxIterations
                );

                dispatch({
                  type: "UPDATE_PROGRESS",
                  payload: {
                    progress: progressResult.overallProgress,
                    message: progressResult.progressMessage,
                  },
                });
              }
            } else if (data.type === "complete") {
              // Generation complete - state was already updated from last 'update' event
              // Calculate execution time
              const executionTime = startTimeRef.current
                ? (Date.now() - startTimeRef.current) / 1000
                : 0;

              // Just mark as complete with 100% progress
              dispatch({
                type: "UPDATE_PROGRESS",
                payload: {
                  progress: 100,
                  message: t("loading_complete"),
                },
              });

              // Update with final execution time
              dispatch({
                type: "UPDATE_STATE",
                payload: {
                  executionTime,
                },
              });

              // Transition to completed state after brief delay
              setTimeout(() => {
                dispatch({ type: "COMPLETE", payload: {} });
                eventSource.close();
                startTimeRef.current = null;
              }, 500);
            } else if (data.type === "cancelled") {
              // Generation was cancelled - confirm cancellation
              // Update progress message to show cancellation message
              dispatch({
                type: "UPDATE_PROGRESS",
                payload: {
                  progress: 0,
                  message: data.message || t("loading_cancelled"),
                },
              });
              // Mark as cancelled (this will hide the GeneratingHeader and show the form)
              dispatch({ type: "CANCEL" });
              eventSource.close();
              startTimeRef.current = null;
            } else if (data.type === "error") {
              // Error occurred
              dispatch({
                type: "ERROR",
                payload: data.message || "An error occurred during generation",
              });
              eventSource.close();
            }
          } catch (error) {
            console.error("Error parsing SSE event:", error);
          }
        };

        eventSource.onerror = (error) => {
          console.error("SSE Error:", error);
          dispatch({
            type: "ERROR",
            payload: "Connection error. Please try again.",
          });
          eventSource.close();
        };
      } catch (error) {
        console.error("Error starting generation:", error);
        dispatch({
          type: "ERROR",
          payload: error instanceof Error ? error.message : "Failed to start generation",
        });
      }
    },
    [dispatch, state]
  );

  /**
   * Cancel ongoing generation
   */
  const cancelGeneration = useCallback(async () => {
    // Set status to "cancelling" immediately when button is pressed
    dispatch({ type: "CANCELLING" });

    if (state.taskId) {
      try {
        await apiCancelGeneration(state.taskId);
        // Don't close EventSource here - wait for "cancelled" event from server
        // The server will send a "cancelled" event which will trigger the CANCEL action
      } catch (error) {
        console.error("Error canceling generation:", error);
        // If API call fails, still close the connection and mark as cancelled
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
          eventSourceRef.current = null;
        }
        dispatch({ type: "CANCEL" });
      }
    } else {
      // No task ID means non-streaming mode - just mark as cancelled
      dispatch({ type: "CANCEL" });
    }
  }, [state.taskId, dispatch]);

  /**
   * Reset generation state
   */
  const resetGeneration = useCallback(() => {
    // Close EventSource if still open
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    dispatch({ type: "RESET" });
  }, [dispatch]);

  return {
    state,
    startGeneration,
    cancelGeneration,
    resetGeneration,
  };
}
