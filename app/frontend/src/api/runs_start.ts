// The Agent's spoken confirmation that a run has started:
// POST /messages/started, streamed. Extracted from `./runs`, which
// re-exports it so callers keep importing from '@/api/runs'.
//
// Mirrors runs_qa.ts's askRunQuestion in transport and runs_interviews.ts's
// streamInterviewTurn in channels: the announcement is written by a thinking
// model, so it relays reasoning as well as prose. Unlike either, it has no
// error frame -- the run has already started when this is called, and no
// failure here changes that, so the server ends a call it cannot complete
// with its own deterministic announcement (see
// run_start_announcement.py::stream_announcement).

import {
  API_BASE_URL,
  byokHeaders,
  fetchWithSession,
  jsonRequest,
  readSseFrames,
} from './runs_http';

/** Where a streamed announcement's two live channels go. */
export interface StartAnnouncementSinks {
  /** Receives each chain-of-thought fragment as the model emits it. */
  onReasoning?: (fragment: string) => void;
  /** Receives each fragment of the announcement as it is written. */
  onChunk?: (fragment: string) => void;
}

/** What one finished announcement tells its caller. */
export interface StartAnnouncement {
  /** True when the deterministic announcement stood in for a model's. */
  fallback: boolean;
}

type StartFrame =
  | {type: 'reasoning'; content: string}
  | {type: 'chunk'; content: string}
  | {type: 'done'; prompt_id: number; fallback: boolean};

/** Relays one frame to its sink; returns the outcome once `done` arrives. */
function applyStartFrame(
  frame: StartFrame,
  sinks: StartAnnouncementSinks,
): StartAnnouncement | null {
  if (frame.type === 'done') return {fallback: frame.fallback};
  const sink = frame.type === 'reasoning' ? sinks.onReasoning : sinks.onChunk;
  sink?.(frame.content);
  return null;
}

/**
 * Sends the scientist's start request to a run that has just been started,
 * and streams the Agent's reply to it.
 *
 * @param runId The run that was started.
 * @param prompt The scientist's own request, persisted verbatim as the user
 *   turn this announcement replies to.
 * @param sinks Where the streamed reasoning/prose are relayed.
 * @param signal Aborts the turn; the partial announcement is dropped and the
 *   caller falls back to the deterministic copy.
 * @returns What the finished announcement resolved to, or null if the stream
 *   ended without a `done` frame.
 */
export async function announceRunStart(
  runId: string,
  prompt: string,
  sinks: StartAnnouncementSinks = {},
  signal?: AbortSignal,
): Promise<StartAnnouncement | null> {
  const init = jsonRequest({prompt}, true);
  const res = await fetchWithSession(
    `${API_BASE_URL}/api/runs/${runId}/messages/started`,
    {
      ...init,
      signal,
      headers: {
        ...(init.headers as Record<string, string>),
        ...byokHeaders(),
      },
    },
  );
  let outcome: StartAnnouncement | null = null;
  for await (const frame of readSseFrames<StartFrame>(res)) {
    outcome = applyStartFrame(frame, sinks) ?? outcome;
  }
  return outcome;
}
