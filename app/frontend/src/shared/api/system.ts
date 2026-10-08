import {clientHeaders, fetchField, fetchJson} from './runs';
import type {SystemStatusResponse} from './wire_system';

// The wire shape is generated from the backend's status model (wire_system.ts).
export type {
  Connector,
  ProbeStatus,
  SystemStatusResponse as SystemStatus,
} from './wire_system';

export function getSystemStatus(): Promise<SystemStatusResponse> {
  return fetchJson('/status');
}

export type ByokModelCatalog = Record<string, string[]>;

export interface FreeUsage {
  // Offline keyless runs incur no provider cost, so free limits are not
  // enforced.
  enforced: boolean;
  tier: 'express';
  // Free allowances are per UTC day; null denotes uncapped usage.
  limit: number | null;
  used: number;
  remaining: number | null;
  // Reset timestamps are Unix seconds at the next UTC midnight.
  resets_at: number;
}

export function fetchByokModelCatalog(): Promise<ByokModelCatalog> {
  return fetchField('/api/byok-models', 'providers', {
    headers: clientHeaders(),
  });
}

export function fetchFreeUsage(): Promise<FreeUsage> {
  return fetchJson('/api/free-usage', {headers: clientHeaders()});
}
