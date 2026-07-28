// Interview API client: the durable model-driven research-goal interview
// (`/api/interviews`). Extracted from `./runs`, which re-exports the public
// functions so callers keep importing them from '@/api/runs'.

import type {Audience, ChatSummary, Interview} from './run_types';
import {
  API_BASE_URL,
  clientHeaders,
  fetchJson,
  jsonRequest,
  readSseFrames,
} from './runs_http';

/** A frame of a streamed interview turn. */
type InterviewFrame =
  | {type: 'reasoning'; content: string}
  | {type: 'interview'; interview: Interview}
  | {type: 'error'; detail: string};

/**
 * Applies one streamed interview frame to the in-progress interview: relays
 * reasoning fragments, adopts a completed interview snapshot, or throws on
 * an error frame. Returns the interview unchanged for a reasoning frame.
 */
function applyInterviewFrame(
  frame: InterviewFrame,
  interview: Interview | undefined,
  onReasoning?: (fragment: string) => void,
): Interview | undefined {
  switch (frame.type) {
    case 'reasoning':
      onReasoning?.(frame.content);
      return interview;
    case 'interview':
      return frame.interview;
    case 'error':
      throw new Error(frame.detail);
  }
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
 * @param onReasoning Receives each chain-of-thought fragment as it arrives.
 * @param method HTTP method; the revision endpoints replace a turn rather
 *   than appending one, so one of them is a PUT.
 */
async function streamInterviewTurn(
  path: string,
  body: unknown,
  onReasoning?: (fragment: string) => void,
  method = 'POST',
): Promise<Interview> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...jsonRequest(body, true),
    method,
  });
  let interview: Interview | undefined;
  for await (const frame of readSseFrames<InterviewFrame>(res)) {
    interview = applyInterviewFrame(frame, interview, onReasoning);
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
  onReasoning?: (fragment: string) => void,
  audience?: Audience,
): Promise<Interview> {
  return streamInterviewTurn(
    '/api/interviews',
    {research_challenge: researchChallenge, audience},
    onReasoning,
  );
}

/** Sends one scientist answer and returns the Agent's updated derivation. */
export async function addInterviewTurn(
  interviewId: string,
  content: string,
  onReasoning?: (fragment: string) => void,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns`,
    {content},
    onReasoning,
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
  onReasoning?: (fragment: string) => void,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns/${turnId}`,
    {content},
    onReasoning,
    'PUT',
  );
}

/** Discards one Agent turn and answers the same prompt again. */
export async function retryInterviewTurn(
  interviewId: string,
  turnId: number,
  onReasoning?: (fragment: string) => void,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns/${turnId}/retry`,
    {},
    onReasoning,
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
