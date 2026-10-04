import {clientHeaders, fetchField, fetchJson} from './runs';

export interface ProbeStatus {
  // Probe error means no availability verdict, unlike definitive up/down.
  state: 'up' | 'down' | 'error';
  error: string | null;
}

export interface Connector {
  id: string;
  display: string;
}

export interface SystemStatus {
  mcp_available: boolean;
  pubmed_available: boolean;
  literature_review_available: boolean;
  web_search_available?: boolean;
  // Without SMTP, offering completion email would promise an operation that can
  // only fail.
  email_notifications_available?: boolean;
  probes: {mcp: ProbeStatus; pubmed: ProbeStatus; web_search?: ProbeStatus};
  mcp_server_url: string;
  // The mock value remains compatible with older deployment responses.
  provider: 'mock' | 'engine';
  llm_backend: 'offline' | 'real';
  has_provider_key: boolean;
  engine_importable: boolean;
  model_name: string;
  supervisor_model_name: string;
  connectors: Connector[];
}

export function getSystemStatus(): Promise<SystemStatus> {
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
