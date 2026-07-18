// System diagnostics API client. Mirrors the /status endpoint in app/main.py.

import {fetchJson} from './runs';

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
  /** Present once the backend advertises the web-search tool. */
  web_search_available?: boolean;
  probes: {mcp: ProbeStatus; pubmed: ProbeStatus; web_search?: ProbeStatus};
  mcp_server_url: string;
  provider: 'mock' | 'engine';
  mock_mode: boolean;
  has_provider_key: boolean;
  engine_importable: boolean;
  model_name: string;
  supervisor_model_name: string;
  connectors: Connector[];
}

/**
 * Fetches the backend's system availability status.
 *
 * @returns Provider/mock-mode info and literature-stack probe results.
 */
export function getSystemStatus(): Promise<SystemStatus> {
  return fetchJson('/status');
}
