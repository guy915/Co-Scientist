import {
  isCancelledStatus,
  isDraftStatus,
  type ChatSummary,
  type Interview,
  type Run,
  type RunFocus,
  type RunTier,
} from '@/api/runs';
import type {InferredRunSpec} from '../run_spec';
import {
  attributeDisplayString,
  criterionDisplayString,
} from '../run_spec_display';
import {type StartedSession} from '../pages/chat_timeline_started_card';
import type {LinkedDraftRecovery} from './chat_session_types';

export type LinkedRun =
  | {chatId: string; runId: string; phase: 'loading'}
  | {chatId: string; runId: string; phase: 'error'}
  | {
      chatId: string;
      runId: string;
      phase: 'ready';
      run: Run;
      recoverySpec?: InferredRunSpec;
    };

export interface PendingRunCreatePayload extends Record<string, unknown> {
  research_goal?: string;
  requirements?: string[];
  attributes?: string[];
  criteria?: string[];
  focus?: RunFocus;
  tier?: RunTier;
  notify_on_completion?: boolean;
  completion_email?: string;
}

export interface LinkedRunTarget {
  chatId: string;
  runId: string;
  chat: ChatSummary | undefined;
  interview: Interview | null;
}

function firstDefined<T>(fallback: T, ...values: (T | undefined)[]): T {
  return values.find(value => value !== undefined) ?? fallback;
}

function whenPresent<A, B>(
  source: A | null | undefined,
  get: (source: A) => B | undefined,
): B | undefined {
  if (source === undefined || source === null) return undefined;
  return get(source);
}

export function recoverySpecForRun(
  target: LinkedRunTarget,
  run: Run,
  payload: PendingRunCreatePayload | undefined,
): InferredRunSpec {
  const setup = run.config.setup;
  const interviewTitle = whenPresent(
    target.interview,
    interview => interview.fields.title,
  );
  const interviewGoal = whenPresent(
    target.interview,
    interview => interview.fields.research_challenge,
  );
  const interviewPreferences = whenPresent(
    target.interview,
    interview => interview.fields.preferences,
  );
  const interviewAttributes = whenPresent(
    target.interview,
    interview => interview.fields.focus_area,
  );
  return {
    interviewId: firstDefined(
      target.chatId,
      whenPresent(target.interview, interview => interview.id),
    ),
    title: firstDefined(
      whenPresent(target.chat, chat => chat.title),
      interviewTitle,
    ),
    goal: firstDefined(
      run.research_goal,
      whenPresent(setup, value => value.goal),
      whenPresent(payload, value => value.research_goal),
      interviewGoal,
    ),
    requirements: firstDefined(
      [],
      whenPresent(setup, value => value.requirements),
      whenPresent(payload, value => value.requirements),
      interviewPreferences,
    ),
    attributes: firstDefined(
      [],
      whenPresent(setup, value => value.attributes.map(attributeDisplayString)),
      whenPresent(payload, value => value.attributes),
      interviewAttributes,
    ),
    criteria: firstDefined(
      [],
      whenPresent(setup, value => value.criteria.map(criterionDisplayString)),
      whenPresent(payload, value => value.criteria),
    ),
    focus: firstDefined(
      'balance',
      whenPresent(setup, value => value.focus),
      run.config.focus,
      whenPresent(payload, value => value.focus),
    ),
    tier: firstDefined(
      'standard',
      whenPresent(setup, value => value.tier),
      run.config.tier,
      whenPresent(payload, value => value.tier),
    ),
    notifyOnCompletion: firstDefined(
      false,
      whenPresent(payload, value => value.notify_on_completion),
    ),
    completionEmail: firstDefined(
      '',
      whenPresent(payload, value => value.completion_email),
    ),
  };
}

export function recoveryStatus(
  linkedRun: LinkedRun | null,
): LinkedDraftRecovery['status'] {
  if (!linkedRun) return undefined;
  if (linkedRun.phase === 'loading') return 'checking';
  if (linkedRun.phase === 'error') return 'error';
  if (isCancelledStatus(linkedRun.run.status)) return 'cancelled';
  return undefined;
}

function recoverySpec(
  linkedRun: LinkedRun | null,
): InferredRunSpec | undefined {
  if (!linkedRun) return undefined;
  if (linkedRun.phase !== 'ready') return undefined;
  return isDraftStatus(linkedRun.run.status)
    ? linkedRun.recoverySpec
    : undefined;
}

export function recoverySummary(
  linkedRun: LinkedRun | null,
): Pick<LinkedDraftRecovery, 'canContinueLinkedDraft' | 'spec'> {
  const spec = recoverySpec(linkedRun);
  return {canContinueLinkedDraft: Boolean(spec), spec};
}

function matchesLinkedRun(
  linkedRun: LinkedRun | null,
  chatId: string | undefined,
  runId: string | null,
): linkedRun is LinkedRun {
  return Boolean(
    runId &&
    linkedRun &&
    linkedRun.chatId === chatId &&
    linkedRun.runId === runId,
  );
}

function isCurrentSessionRun(
  startedSession: StartedSession | null,
  runId: string | null,
): boolean {
  return startedSession?.id === runId;
}

export function currentLinkedRun(
  chatId: string | undefined,
  runId: string | null,
  linkedRun: LinkedRun | null,
  startedSession: StartedSession | null,
): LinkedRun | null {
  if (!runId) return null;
  if (isCurrentSessionRun(startedSession, runId)) return null;
  if (matchesLinkedRun(linkedRun, chatId, runId)) return linkedRun;
  return {chatId: chatId ?? '', runId, phase: 'loading'};
}
