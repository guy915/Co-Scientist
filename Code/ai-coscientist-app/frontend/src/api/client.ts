import type { GenerateRequest, GenerateResponse } from "@/types/workflow";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8008";

export interface HealthResponse {
  status: string;
  version: string;
  model_name: string;
}

export interface ConfigResponse {
  max_iterations: number;
  initial_hypotheses_count: number;
  evolution_max_count: number;
}

export interface SystemStatusResponse {
  mcp_available: boolean;
  pubmed_available: boolean;
  literature_review_available: boolean;
  mcp_server_url: string;
  entrez_email_configured: boolean;
}

/**
 * Generate hypotheses (non-streaming)
 */
export async function generateHypotheses(request: GenerateRequest): Promise<GenerateResponse> {
  const response = await fetch(`${API_BASE_URL}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Generation failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Start hypothesis generation (returns task_id)
 */
export async function startGeneration(
  request: GenerateRequest
): Promise<{ task_id: string; status: string }> {
  const response = await fetch(`${API_BASE_URL}/generate/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Failed to start generation: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Create streaming URL for SSE connection using task_id
 */
export function createStreamingURL(taskId: string): string {
  return `${API_BASE_URL}/generate/stream/${taskId}`;
}

/**
 * Cancel hypothesis generation
 */
export async function cancelGeneration(taskId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/cancel_hypothesis_generation`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId }),
  });

  if (!response.ok) {
    throw new Error(`Cancel failed: ${response.statusText}`);
  }
}

/**
 * Check API health
 */
export async function checkHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);

  if (!response.ok) {
    throw new Error("Health check failed");
  }

  return response.json();
}

// Module-level cache for config
let configCache: ConfigResponse | null = null;
let configPromise: Promise<ConfigResponse> | null = null;

/**
 * Get default configuration values (cached)
 * Fetches once per app session, subsequent calls return cached value
 */
export async function getConfig(): Promise<ConfigResponse> {
  // Return cached value if available
  if (configCache !== null) {
    return configCache;
  }

  // Return existing promise if fetch is in progress
  if (configPromise !== null) {
    return configPromise;
  }

  // Start new fetch
  configPromise = fetch(`${API_BASE_URL}/config`)
    .then((response) => {
      if (!response.ok) {
        throw new Error("Failed to fetch config");
      }
      return response.json();
    })
    .then((config) => {
      configCache = config;
      configPromise = null;
      return config;
    })
    .catch((error) => {
      configPromise = null;
      throw error;
    });

  return configPromise;
}

// module-level cache for system status
let statusCache: SystemStatusResponse | null = null;
let statusPromise: Promise<SystemStatusResponse> | null = null;

/**
 * get system availability status (cached)
 * fetches once per app session, subsequent calls return cached value
 */
export async function getSystemStatus(): Promise<SystemStatusResponse> {
  // return cached value if available
  if (statusCache !== null) {
    return statusCache;
  }

  // return existing promise if fetch is in progress
  if (statusPromise !== null) {
    return statusPromise;
  }

  // start new fetch
  statusPromise = fetch(`${API_BASE_URL}/status`)
    .then((response) => {
      if (!response.ok) {
        throw new Error("failed to fetch system status");
      }
      return response.json();
    })
    .then((status) => {
      statusCache = status;
      statusPromise = null;
      return status;
    })
    .catch((error) => {
      statusPromise = null;
      throw error;
    });

  return statusPromise;
}
