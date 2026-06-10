// Run lifecycle API client. Mirrors the FastAPI router in app/runs.py.

import { getClientId } from "@/lib/clientId";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || "";

function clientHeaders(): Record<string, string> {
  return { "X-Client-ID": getClientId() };
}

export type RunStatus =
  | "draft"
  | "queued"
  | "running"
  | "synthesizing"
  | "completed"
  | "failed"
  | "blocked"
  | "cancelled";

export type RunProfile = "standard" | "advanced";

export interface Run {
  id: string;
  research_goal: string;
  profile: RunProfile;
  status: RunStatus;
  provider: "mock" | "engine";
  config: Record<string, number | string>;
  created_at: number;
  updated_at: number;
  completed_at: number | null;
  error: string | null;
}

export interface RunSummary {
  events: number;
  hypotheses: number;
  evidence: number;
  matches: number;
  reviews: number;
}

export interface RunWithSummary extends Run {
  summary: RunSummary;
}

export interface Hypothesis {
  id: string;
  run_id: string;
  parent_id: string | null;
  generation: number;
  title: string;
  statement: string;
  mechanism: string | null;
  expected_effect: string | null;
  experimental_context: string | null;
  created_by_agent: string;
  created_at: number;
  elo_rating: number;
  win_count: number;
  loss_count: number;
  novelty_score: number | null;
  plausibility_score: number | null;
  testability_score: number | null;
  safety_status: string | null;
  status: string | null;
  cluster_id: string | null;
}

export interface Evidence {
  id: string;
  title: string;
  source: string;
  url: string;
  authors: string[];
  year: number | null;
  abstract: string;
  available: boolean;
}

export interface MatchRow {
  id: number;
  iteration: number;
  winner_id: string;
  loser_id: string;
  winner_elo_before: number;
  winner_elo_after: number;
  loser_elo_before: number;
  loser_elo_after: number;
  rationale: string;
  created_at: number;
}

export interface Review {
  id: number;
  hypothesis_id: string;
  reviewer_agent: string;
  summary: string;
  critique: string;
  novelty: number | null;
  plausibility: number | null;
  testability: number | null;
  overall: number | null;
}

export interface SafetyDecision {
  stage: "intake" | "final";
  decision: "allow" | "redact" | "block";
  reason: string;
  matches: string[];
  created_at: number;
}

export interface CitationRow {
  id: number;
  hypothesis_id: string;
  evidence_id: string;
  claim: string;
  state: "verified" | "partial" | "unsupported" | "unavailable";
}

export interface ReportPayload {
  research_goal: string;
  profile: RunProfile;
  provider: string;
  leaderboard: { id: string; title: string; elo: number }[];
  citation_summary?: Record<string, number>;
  evidence_count?: number;
  matches_count?: number;
}

export interface Report {
  id: string;
  run_id: string;
  payload: ReportPayload;
  markdown_path: string;
  created_at: number;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

export async function createRun(input: {
  research_goal: string;
  profile: RunProfile;
  initial_hypotheses_count?: number;
  max_iterations?: number;
  evolution_max_count?: number;
  k_factor?: number;
}): Promise<Run> {
  const res = await fetch(`${API_BASE_URL}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...clientHeaders() },
    body: JSON.stringify(input),
  });
  return jsonOrThrow<Run>(res);
}

export async function listRuns(): Promise<Run[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs`, { headers: clientHeaders() });
  const data = await jsonOrThrow<{ runs: Run[] }>(res);
  return data.runs;
}

export async function getRun(id: string): Promise<RunWithSummary> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}`);
  return jsonOrThrow<RunWithSummary>(res);
}

export async function startRun(
  id: string,
  body: { force_provider?: "mock" | "engine" } = {}
): Promise<{ id: string; status: string }> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res);
}

export async function cancelRun(id: string): Promise<{ id: string; status: string }> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/cancel`, {
    method: "POST",
  });
  return jsonOrThrow(res);
}

export async function getHypotheses(id: string): Promise<Hypothesis[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/hypotheses`);
  const data = await jsonOrThrow<{ hypotheses: Hypothesis[] }>(res);
  return data.hypotheses;
}

export async function getEvidence(id: string): Promise<Evidence[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/evidence`);
  const data = await jsonOrThrow<{ evidence: Evidence[] }>(res);
  return data.evidence;
}

export async function getMatches(id: string): Promise<MatchRow[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/matches`);
  const data = await jsonOrThrow<{ matches: MatchRow[] }>(res);
  return data.matches;
}

export async function getReviews(id: string): Promise<Review[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/reviews`);
  const data = await jsonOrThrow<{ reviews: Review[] }>(res);
  return data.reviews;
}

export async function getSafety(id: string): Promise<SafetyDecision[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/safety`);
  const data = await jsonOrThrow<{ safety: SafetyDecision[] }>(res);
  return data.safety;
}

export async function getCitations(id: string): Promise<CitationRow[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/citations`);
  const data = await jsonOrThrow<{ citations: CitationRow[] }>(res);
  return data.citations;
}

export async function getReport(id: string): Promise<Report | null> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/report`);
  if (res.status === 404) return null;
  return jsonOrThrow<Report>(res);
}

export function reportMarkdownUrl(id: string): string {
  return `${API_BASE_URL}/api/runs/${id}/report.md`;
}

export function eventsStreamUrl(id: string, after = 0): string {
  return `${API_BASE_URL}/api/runs/${id}/events?after=${after}`;
}

export interface RunEvent {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: number;
}

export async function getRunEventsLog(id: string): Promise<RunEvent[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/events/log`);
  return jsonOrThrow<RunEvent[]>(res);
}

export interface SystemStatus {
  mcp_available: boolean;
  pubmed_available: boolean;
  literature_review_available: boolean;
  mcp_server_url: string;
  provider: "mock" | "engine";
  mock_mode: boolean;
  has_provider_key: boolean;
  engine_importable: boolean;
  model_name: string;
}

export async function getSystemStatus(): Promise<SystemStatus> {
  const res = await fetch(`${API_BASE_URL}/status`);
  return jsonOrThrow<SystemStatus>(res);
}
