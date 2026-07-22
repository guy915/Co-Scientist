// Interview API client: the durable model-driven research-goal interview
// (`/api/interviews`). Extracted from `./runs`, which re-exports the public
// functions so callers keep importing them from '@/api/runs'.

import type {Audience, Interview} from './run_types';
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
 * Runs one streamed interview turn, relaying the model's live reasoning.
 *
 * The turn streams so the chain of thought can be shown while the Agent is
 * still composing, but the transport stays an implementation detail: callers
 * await the resolved interview exactly as they did over plain JSON.
 *
 * @param path The interview endpoint to post to.
 * @param body The JSON request body.
 * @param onReasoning Receives each chain-of-thought fragment as it arrives.
 */
async function streamInterviewTurn(
  path: string,
  body: unknown,
  onReasoning?: (fragment: string) => void,
): Promise<Interview> {
  const res = await fetch(`${API_BASE_URL}${path}`, jsonRequest(body, true));
  let interview: Interview | undefined;
  for await (const frame of readSseFrames<InterviewFrame>(res)) {
    if (frame.type === 'reasoning') onReasoning?.(frame.content);
    else if (frame.type === 'interview') interview = frame.interview;
    else if (frame.type === 'error') throw new Error(frame.detail);
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
