import type { GenerationState } from "@/types/workflow";

const STORAGE_KEY = "hypothesis-generation-last-run";

/**
 * Save the last completed run state to sessionStorage
 * Overwrites any previous saved state
 */
export function saveLastRunState(state: GenerationState): void {
  try {
    const json = JSON.stringify(state);
    sessionStorage.setItem(STORAGE_KEY, json);
    console.log("[Persistence] Saved last run state to sessionStorage");
  } catch (error) {
    // Handle quota exceeded or other errors gracefully
    if (error instanceof DOMException && error.name === "QuotaExceededError") {
      console.warn("[Persistence] sessionStorage quota exceeded, clearing old data");
      // Clear and retry
      sessionStorage.removeItem(STORAGE_KEY);
      try {
        sessionStorage.setItem(STORAGE_KEY, json);
        console.log("[Persistence] Successfully saved after clearing old data");
      } catch (retryError) {
        console.error("[Persistence] Failed to save even after clearing:", retryError);
      }
    } else {
      console.error("[Persistence] Failed to save state:", error);
    }
  }
}

/**
 * Load the last completed run state from sessionStorage
 * Returns null if no valid state is found
 */
export function loadLastRunState(): GenerationState | null {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (!stored) return null;

    const state = JSON.parse(stored) as GenerationState;
    // Validate it's a completed run with hypotheses
    if (state.status === "completed" && state.hypotheses && state.hypotheses.length > 0) {
      console.log("[Persistence] Loaded last run state from sessionStorage");
      return state;
    }
    // If invalid, clear it
    sessionStorage.removeItem(STORAGE_KEY);
    return null;
  } catch (error) {
    console.error("[Persistence] Failed to load state:", error);
    // Clear corrupted data
    sessionStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

/**
 * Clear the saved state from sessionStorage
 */
export function clearLastRunState(): void {
  sessionStorage.removeItem(STORAGE_KEY);
  console.log("[Persistence] Cleared saved state from sessionStorage");
}
