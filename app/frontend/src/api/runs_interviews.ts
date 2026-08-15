// Interview API client: the durable model-driven research-goal interview
// (`/api/interviews`). Extracted from `./runs`, which re-exports the public
// functions so callers keep importing them from '@/api/runs'.

import type {Audience, ChatSummary, Interview} from './run_types';
import {
  API_BASE_URL,
  byokHeaders,
  clientHeaders,
  fetchJson,
  jsonRequest,
  readSseFrames,
} from './runs_http';

/** A frame of a streamed interview turn. */
type InterviewFrame =
  | {type: 'reasoning'; content: string}
  | {type: 'chunk'; content: string}
  | {type: 'interview'; interview: Interview}
  | {type: 'error'; detail: string};

/**
 * Where a streamed turn's two live channels go.
 *
 * A turn streams the Agent's chain of thought and then its answer, so both
 * arrive while it is still being composed. Bundled rather than passed as two
 * positional callbacks, so a caller wanting only one names the one it wants
 * and the four turn functions below keep their existing argument order.
 */
export interface InterviewSinks {
  /** Receives each chain-of-thought fragment as it arrives. */
  onReasoning?: (fragment: string) => void;
  /** Receives each fragment of the answer's prose as it is written. */
  onProse?: (fragment: string) => void;
}

/**
 * Applies one streamed interview frame to the in-progress interview: relays
 * a reasoning or prose fragment, adopts a completed interview snapshot, or
 * throws on an error frame. Returns the interview unchanged for a fragment.
 *
 * The two terminal frames are handled first so what remains is a live
 * fragment differing only in which channel it belongs to.
 */
function applyInterviewFrame(
  frame: InterviewFrame,
  interview: Interview | undefined,
  sinks: InterviewSinks,
): Interview | undefined {
  if (frame.type === 'interview') return frame.interview;
  if (frame.type === 'error') throw new Error(frame.detail);
  const sink = frame.type === 'reasoning' ? sinks.onReasoning : sinks.onProse;
  sink?.(frame.content);
  return interview;
}

/**
 * Runs one streamed interview turn, relaying the model's live reasoning.
 *
 * The turn streams so the chain of thought can be shown while the Agent is
 * still composing, but the transport stays an implementation detail: callers
 * await the resolved interview exactly as they did over plain JSON.
 *
 * @param path The interview endpoint to post to.
 * @param body The JSON request body.
 * @param sinks Where the turn's live reasoning and prose are relayed.
 * @param method HTTP method; the revision endpoints replace a turn rather
 *   than appending one, so one of them is a PUT.
 */
async function streamInterviewTurn(
  path: string,
  body: unknown,
  sinks: InterviewSinks = {},
  method = 'POST',
): Promise<Interview> {
  const init = jsonRequest(body, true);
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    method,
    headers: {
      ...(init.headers as Record<string, string>),
      ...byokHeaders(),
    },
  });
  let interview: Interview | undefined;
  for await (const frame of readSseFrames<InterviewFrame>(res)) {
    interview = applyInterviewFrame(frame, interview, sinks);
  }
  if (!interview) {
    throw new Error('The Agent could not continue the interview.');
  }
  return interview;
}

/**
 * Starts a durable model-driven research-goal interview.
 *
 * The audience is sent once, at creation: the server stores it on the
 * interview so every later turn is conducted with the same lab context,
 * which is also what lets the Agent answer questions about the group.
 */
export async function createInterview(
  researchChallenge: string,
  sinks?: InterviewSinks,
  audience?: Audience,
  documentIds: string[] = [],
): Promise<Interview> {
  return streamInterviewTurn(
    '/api/interviews',
    {
      research_challenge: researchChallenge,
      audience,
      document_ids: documentIds,
    },
    sinks,
  );
}

/**
 * Sends one scientist answer and returns the Agent's updated derivation.
 *
 * `documentIds` names documents staged through `/api/documents` with this
 * turn; the Agent reads them while deriving it, so an attachment shapes the
 * conversation it was made in rather than arriving after the plan is set.
 */
export async function addInterviewTurn(
  interviewId: string,
  content: string,
  sinks?: InterviewSinks,
  documentIds: string[] = [],
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns`,
    {content, document_ids: documentIds},
    sinks,
  );
}

/**
 * Rewrites one scientist turn in place and re-answers from there.
 *
 * The edited prompt replaces the original where it stands; every turn the
 * Agent derived from the old wording is discarded with it, so the returned
 * interview is the whole conversation as it now reads.
 */
export async function editInterviewTurn(
  interviewId: string,
  turnId: number,
  content: string,
  sinks?: InterviewSinks,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns/${turnId}`,
    {content},
    sinks,
    'PUT',
  );
}

/** Discards one Agent turn and answers the same prompt again. */
export async function retryInterviewTurn(
  interviewId: string,
  turnId: number,
  sinks?: InterviewSinks,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns/${turnId}/retry`,
    {},
    sinks,
  );
}

/**
 * Lists the caller's chats, newest first, for the sidebar.
 *
 * Transcripts are deliberately absent: the list only needs a label and the
 * run each chat started, and a chat is reopened by id when it is clicked.
 */
export async function listInterviews(): Promise<ChatSummary[]> {
  return fetchJson('/api/interviews', {headers: clientHeaders()});
}

/** Reloads a durable interview for resume. */
export async function getInterview(interviewId: string): Promise<Interview> {
  return fetchJson(`/api/interviews/${interviewId}`, {
    headers: clientHeaders(),
  });
}

/** Persists scientist edits to the four verified fields. */
export async function editInterviewFields(
  interviewId: string,
  fields: Interview['fields'],
): Promise<Interview> {
  return fetchJson(
    `/api/interviews/${interviewId}/fields`,
    jsonRequest(fields, true),
  );
}
