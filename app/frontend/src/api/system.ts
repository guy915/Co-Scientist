import {clientHeaders, fetchField, fetchJson} from './runs';

// System diagnostics API client. Mirrors the /status endpoint in app/main.py.

/** Detailed outcome of one backend availability probe. */
export interface ProbeStatus {
  /** 'up' | 'down' are definitive answers; 'error' means the probe failed. */
  state: 'up' | 'down' | 'error';
  error: string | null;
}

/** One data-source connector shown in the composer's connectors menu. */
export interface Connector {
  id: string;
  display: string;
}

/** The `/status` response: availability probes plus provider diagnostics. */
export interface SystemStatus {
  mcp_available: boolean;
  pubmed_available: boolean;
  literature_review_available: boolean;
  /** Whether a web search would reach a provider, key included. */
  web_search_available?: boolean;
  /**
   * Whether an SMTP transport is configured. False means a completion-email
   * opt-in could only ever fail, so the plan card does not offer one.
   */
  email_notifications_available?: boolean;
  probes: {mcp: ProbeStatus; pubmed: ProbeStatus; web_search?: ProbeStatus};
  mcp_server_url: string;
  // The engine is the only workflow provider now; 'mock' only ever appears
  // on a response mirroring a pre-unification deployment.
  provider: 'mock' | 'engine';
  /** Active LLM backend: 'offline' (deterministic router) | 'real'. */
  llm_backend: 'offline' | 'real';
  has_provider_key: boolean;
  engine_importable: boolean;
  model_name: string;
  supervisor_model_name: string;
  connectors: Connector[];
}

/**
 * Fetches the backend's system availability status.
 *
 * @returns Provider/offline-backend info and literature-stack probe results.
 */
export function getSystemStatus(): Promise<SystemStatus> {
  return fetchJson('/status');
}

// Model-choice and free-usage API client for Settings > Model. Mirrors
// GET /api/byok-models (app/byok_models.py) and GET /api/free-usage
// (app/free_usage.py).

/** Models each BYOK provider offers, keyed by provider, default first. */
export type ByokModelCatalog = Record<string, string[]>;

/** The caller's free-usage state: runs with no API key of their own. */
export interface FreeUsage {
  /** False on an offline deployment, where keyless runs cost nothing. */
  enforced: boolean;
  /** The only run type free usage may start. */
  tier: 'express';
  /** Free runs allowed per UTC day, or null when uncapped. */
  limit: number | null;
  used: number;
  remaining: number | null;
  /** Epoch seconds at which today's count resets (next UTC midnight). */
  resets_at: number;
}

/** Fetches the models each BYOK provider offers. */
export function fetchByokModelCatalog(): Promise<ByokModelCatalog> {
  return fetchField('/api/byok-models', 'providers', {
    headers: clientHeaders(),
  });
}

/** Fetches how many free runs the caller has left today. */
export function fetchFreeUsage(): Promise<FreeUsage> {
  return fetchJson('/api/free-usage', {headers: clientHeaders()});
}
