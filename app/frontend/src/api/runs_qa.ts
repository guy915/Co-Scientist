// Grounded Q&A client for a started run: POST /messages/ask (streamed
// answer) and GET /messages (rehydration). Extracted from `./runs`, which
// re-exports both so callers keep importing from '@/api/runs'.
//
// Mirrors runs_interviews.ts's streamInterviewTurn: the transport streams so
// the chat timeline can show the answer as it is written, but the frame
// handling stays out of the caller's way. Unlike an interview turn, there is
// no `reasoning` frame -- see qa.py::stream_answer -- so QaSinks carries one
// fewer channel than InterviewSinks.

import type {Audience, QaSource, RunMessage} from './run_types';
import {
  API_BASE_URL,
  byokHeaders,
  clientHeaders,
  fetchField,
  jsonRequest,
  readSseFrames,
} from './runs_http';

export type {QaSource, RunMessage} from './run_types';

/** Where a streamed Q&A answer's two live channels go. */
export interface QaSinks {
  /** The evidence manifest, delivered once before any chunk arrives. */
  onSources?: (sources: QaSource[]) => void;
  /** Receives each fragment of the answer's prose as it is written. */
  onChunk?: (fragment: string) => void;
}

type AskFrame =
  | {type: 'sources'; sources: QaSource[]}
  | {type: 'chunk'; content: string}
  | {type: 'done'; question_id: number}
  | {type: 'error'; message: string};

/** Relays a sources or chunk frame to its sink; a no-op for any other type. */
function relayAskFrame(frame: AskFrame, sinks: QaSinks): void {
  if (frame.type === 'sources') sinks.onSources?.(frame.sources);
  if (frame.type === 'chunk') sinks.onChunk?.(frame.content);
}

/**
 * Applies one streamed ask frame: relays a sources/chunk fragment to its
 * sink, or throws on an error frame (the run's Q&A stream persists a
 * fallback answer before emitting this, so the caller only needs to surface
 * it -- see qa.py::_handle_qa_stream_error). Returns the persisted
 * question's message id once `done` arrives, else `questionId` unchanged.
 */
function applyAskFrame(
  frame: AskFrame,
  questionId: number | undefined,
  sinks: QaSinks,
): number | undefined {
  if (frame.type === 'done') return frame.question_id;
  if (frame.type === 'error') throw new Error(frame.message);
  relayAskFrame(frame, sinks);
  return questionId;
}

/**
 * Streams one grounded Q&A answer for a started run.
 *
 * @param runId The run being asked about.
 * @param question The scientist's question.
 * @param sinks Where the streamed sources/chunks are relayed.
 * @param audience Optional audience claim (the same corpus-audience gate
 *   run creation and the interview apply).
 * @param signal Aborts the turn -- the fetch itself if not yet sent, or the
 *   read loop if the stream is already open; see the composer's Stop
 *   control. The partial answer is never persisted server-side on abort
 *   (qa.py persists only after the full stream completes), so a caller
 *   simply drops what it has -- there is nothing to resync.
 * @returns The persisted question's message id, once the stream completes.
 */
export async function askRunQuestion(
  runId: string,
  question: string,
  sinks: QaSinks = {},
  audience?: Audience,
  signal?: AbortSignal,
): Promise<number | undefined> {
  const init = jsonRequest({question, audience}, true);
  const res = await fetch(`${API_BASE_URL}/api/runs/${runId}/messages/ask`, {
    ...init,
    signal,
    headers: {
      ...(init.headers as Record<string, string>),
      ...byokHeaders(),
    },
  });
  let questionId: number | undefined;
  for await (const frame of readSseFrames<AskFrame>(res)) {
    questionId = applyAskFrame(frame, questionId, sinks);
  }
  return questionId;
}

/**
 * Fetches every message persisted for a run, in chronological order --
 * both scientist steering (`kind: "steering"`) and grounded Q&A
 * (`kind: "qa"`) rows. Callers filter by `kind`; see
 * chat_session_qa_transcript.ts for the Q&A rehydration path.
 */
export function getRunMessages(runId: string): Promise<RunMessage[]> {
  return fetchField(`/api/runs/${runId}/messages`, 'messages', {
    headers: clientHeaders(),
  });
}
