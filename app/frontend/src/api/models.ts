// Model-choice and free-usage API client for Settings > Model. Mirrors
// GET /api/byok-models (app/byok_models.py) and GET /api/free-usage
// (app/free_usage.py).

import {clientHeaders, fetchField, fetchJson} from './runs_http';

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
