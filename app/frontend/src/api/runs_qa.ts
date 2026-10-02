import type {QaSource, RunMessage} from './run_types';
import {clientHeaders, fetchField, streamJson} from './runs_http';

export type {QaSource, RunMessage} from './run_types';

/** Where a streamed Q&A answer's three live channels go. */
export interface QaSinks {
  /** The evidence manifest, delivered once before any chunk arrives. */
  onSources?: (sources: QaSource[]) => void;
  /** Receives each fragment of the model's chain of thought, before the
   * answer's own prose starts arriving. */
  onReasoning?: (fragment: string) => void;
  /** Receives each fragment of the answer's prose as it is written. */
  onChunk?: (fragment: string) => void;
}

type AskFrame =
  | {type: 'sources'; sources: QaSource[]}
  | {type: 'reasoning'; content: string}
  | {type: 'chunk'; content: string}
  | {type: 'done'; question_id: number}
  | {type: 'error'; message: string};

/** Stream an answer; aborted partial answers are never persisted. */
export async function askRunQuestion(
  runId: string,
  question: string,
  sinks: QaSinks = {},
  signal?: AbortSignal,
): Promise<number | undefined> {
  let questionId: number | undefined;
  for await (const frame of streamJson<AskFrame>(
    `/api/runs/${runId}/messages/ask`,
    {question},
    signal,
  )) {
    switch (frame.type) {
      case 'sources':
        sinks.onSources?.(frame.sources);
        break;
      case 'reasoning':
        sinks.onReasoning?.(frame.content);
        break;
      case 'chunk':
        sinks.onChunk?.(frame.content);
        break;
      case 'done':
        questionId = frame.question_id;
        break;
      case 'error':
        throw new Error(frame.message);
    }
  }
  return questionId;
}

/** Reload chronological steering and Q&A messages; callers filter by kind. */
export function getRunMessages(runId: string): Promise<RunMessage[]> {
  return fetchField(`/api/runs/${runId}/messages`, 'messages', {
    headers: clientHeaders(),
  });
}

export type StartAnnouncementSinks = Pick<QaSinks, 'onReasoning' | 'onChunk'>;

export interface StartAnnouncement {
  /** True when the server used its deterministic announcement. */
  fallback: boolean;
}

type StartFrame =
  | {type: 'reasoning'; content: string}
  | {type: 'chunk'; content: string}
  | {type: 'done'; prompt_id: number; fallback: boolean};

/** Announce an already-started run; failure here cannot change its status. */
export async function announceRunStart(
  runId: string,
  prompt: string,
  sinks: StartAnnouncementSinks = {},
  signal?: AbortSignal,
): Promise<StartAnnouncement | null> {
  let outcome: StartAnnouncement | null = null;
  for await (const frame of streamJson<StartFrame>(
    `/api/runs/${runId}/messages/started`,
    {prompt},
    signal,
  )) {
    if (frame.type === 'done') {
      outcome = {fallback: frame.fallback};
    } else {
      const sink =
        frame.type === 'reasoning' ? sinks.onReasoning : sinks.onChunk;
      sink?.(frame.content);
    }
  }
  return outcome;
}
