import type {ChatSummary, Interview} from './run_types';
import {clientHeaders, fetchJson, jsonRequest, streamJson} from './runs_http';

/** A frame of a streamed interview turn. */
type InterviewFrame =
  | {type: 'reasoning'; content: string}
  | {type: 'chunk'; content: string}
  | {type: 'interview'; interview: Interview}
  | {type: 'error'; detail: string};

export interface InterviewSinks {
  /** Receives each chain-of-thought fragment as it arrives. */
  onReasoning?: (fragment: string) => void;
  /** Receives each fragment of the answer's prose as it is written. */
  onProse?: (fragment: string) => void;
}

/** Relay live fragments and return the final durable interview snapshot. */
async function streamInterviewTurn(
  path: string,
  body: unknown,
  sinks: InterviewSinks = {},
  method = 'POST',
  signal?: AbortSignal,
): Promise<Interview> {
  let interview: Interview | undefined;
  for await (const frame of streamJson<InterviewFrame>(
    path,
    body,
    signal,
    method,
  )) {
    switch (frame.type) {
      case 'interview':
        interview = frame.interview;
        break;
      case 'error':
        throw new Error(frame.detail);
      case 'reasoning':
        sinks.onReasoning?.(frame.content);
        break;
      case 'chunk':
        sinks.onProse?.(frame.content);
    }
  }
  if (!interview) {
    throw new Error('The Agent could not continue the interview.');
  }
  return interview;
}

/** Starts a durable model-driven research-goal interview. */
export function createInterview(
  researchChallenge: string,
  sinks?: InterviewSinks,
  documentIds: string[] = [],
  signal?: AbortSignal,
): Promise<Interview> {
  return streamInterviewTurn(
    '/api/interviews',
    {
      research_challenge: researchChallenge,
      document_ids: documentIds,
    },
    sinks,
    'POST',
    signal,
  );
}

/** Staged documents shape this turn while the Agent derives its answer. */
export function addInterviewTurn(
  interviewId: string,
  content: string,
  sinks?: InterviewSinks,
  documentIds: string[] = [],
  signal?: AbortSignal,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns`,
    {content, document_ids: documentIds},
    sinks,
    'POST',
    signal,
  );
}

/** Replace a scientist turn and discard/rederive everything after it. */
export function editInterviewTurn(
  interviewId: string,
  turnId: number,
  content: string,
  sinks?: InterviewSinks,
  signal?: AbortSignal,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns/${turnId}`,
    {content},
    sinks,
    'PUT',
    signal,
  );
}

/** Discards one Agent turn and answers the same prompt again. */
export function retryInterviewTurn(
  interviewId: string,
  turnId: number,
  sinks?: InterviewSinks,
  signal?: AbortSignal,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns/${turnId}/retry`,
    {},
    sinks,
    'POST',
    signal,
  );
}

/** Sidebar summaries omit transcripts; reopen a conversation by id. */
export function listInterviews(): Promise<ChatSummary[]> {
  return fetchJson('/api/interviews', {headers: clientHeaders()});
}

/** Reloads a durable interview for resume. */
export function getInterview(interviewId: string): Promise<Interview> {
  return fetchJson(`/api/interviews/${interviewId}`, {
    headers: clientHeaders(),
  });
}

/** Persist scientist edits to the four verified fields. */
export function editInterviewFields(
  interviewId: string,
  fields: Interview['fields'],
): Promise<Interview> {
  return fetchJson(`/api/interviews/${interviewId}/fields`, {
    ...jsonRequest(fields, true),
    method: 'PUT',
  });
}
