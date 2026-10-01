import {
  cancelRun,
  createRun,
  getRun,
  isCancelledStatus,
  isDraftStatus,
  isFailureStatus,
  isStartedStatus,
  retiresStartIntent,
  startRun,
  type Run,
} from '@/api/runs';
import {
  getPendingCreateIntent,
  readPendingCreateIntent,
  rememberPendingCreateRun,
  retirePendingCreateIntent,
  type PendingCreateIntent,
} from './chat_session_create_intent';
import {
  recoverySpecForRun,
  type LinkedRunTarget,
  type PendingRunCreatePayload,
} from './chat_linked_run_recovery';
import {
  type ExecuteStartDeps,
  type HandlerDeps,
  type SpecStage,
} from './chat_session_types';

type SettleDeps = Pick<
  ExecuteStartDeps,
  'setDraft' | 'setConfirmed' | 'stageToStart'
>;
export type StartRecoveryDeps = ExecuteStartDeps &
  Pick<HandlerDeps, 'draft' | 'interview'>;
type CreateRunPayload = Parameters<typeof createRun>[0];
type StartDisposition = 'started' | 'already-started';

export interface ResolvedStartTarget {
  runId: string;
  status: string;
  intent?: PendingCreateIntent;
  stage?: SpecStage;
  run: Run;
}

function buildCreateRunPayload(deps: ExecuteStartDeps): CreateRunPayload {
  const spec = deps.stageToStart.spec;
  return {
    research_goal: spec.goal,
    interview_id: spec.interviewId,
    requirements: spec.requirements,
    attributes: spec.attributes,
    criteria: spec.criteria,
    focus: spec.focus,
    tier: spec.tier,
    notify_on_completion: Boolean(spec.notifyOnCompletion),
    completion_email: spec.notifyOnCompletion
      ? spec.completionEmail
      : undefined,
    enable_literature_review: deps.pubmedEnabled,
    enable_web_search: deps.webSearchEnabled,
    // Creation copies staged documents into the run's corpus.
    document_ids: deps.pendingAttachments.map(document => document.id),
  };
}

export async function startOrSettle(
  runId: string,
  chatId: string | undefined,
  intent: PendingCreateIntent | undefined,
  deps: SettleDeps,
): Promise<StartDisposition> {
  try {
    await startRun(runId);
    retireIntent(chatId, intent);
    return 'started';
  } catch (error) {
    return resolveStartError(runId, chatId, intent, deps, error);
  }
}

async function resolveStartError(
  runId: string,
  chatId: string | undefined,
  intent: PendingCreateIntent | undefined,
  deps: SettleDeps,
  error: unknown,
): Promise<StartDisposition> {
  const status = await readRunStatus(runId);
  if (isStartedStatus(status)) {
    retireIntent(chatId, intent);
    return 'already-started';
  }
  if (isDraftStatus(status)) {
    return resolveDraftAfterFailedStart(runId, chatId, intent, deps, error);
  }
  if (isCancelledStatus(status)) retireIntent(chatId, intent);
  restoreDraft(deps);
  throw startErrorForStatus(status) ?? error;
}

async function resolveDraftAfterFailedStart(
  runId: string,
  chatId: string | undefined,
  intent: PendingCreateIntent | undefined,
  deps: SettleDeps,
  error: unknown,
): Promise<StartDisposition> {
  const status = await cancelAndReadStatus(runId);
  if (isCancelledStatus(status)) retireIntent(chatId, intent);
  if (isStartedStatus(status)) {
    retireIntent(chatId, intent);
    return 'already-started';
  }
  restoreDraft(deps);
  throw error;
}

async function cancelAndReadStatus(runId: string): Promise<string | undefined> {
  const cancellation = await cancelRun(runId).catch(() => undefined);
  if (isCancelledStatus(cancellation?.status)) return 'cancelled';
  // A lost cancel response may mean the run started between the requests.
  return readRunStatus(runId);
}

export function retireIntent(
  chatId: string | undefined,
  intent: PendingCreateIntent | undefined,
): void {
  if (chatId && intent) retirePendingCreateIntent(chatId, intent.key);
}

async function readRunStatus(runId: string): Promise<string | undefined> {
  try {
    return (await getRun(runId)).status;
  } catch {
    return undefined;
  }
}

function restoreDraft(deps: SettleDeps): void {
  deps.setConfirmed(null);
  deps.setDraft(deps.stageToStart);
}

export function runOutcomeError(status: string): Error {
  return new Error(
    `The existing run is ${status}. Open its details to review it before retrying.`,
  );
}

function startErrorForStatus(status: string | undefined): Error | undefined {
  if (isFailureStatus(status)) return runOutcomeError(status);
}

async function readStartIntent(
  chatId: string | undefined,
): Promise<PendingCreateIntent<CreateRunPayload> | undefined> {
  if (!chatId) return undefined;
  return readPendingCreateIntent<CreateRunPayload>(chatId);
}

function linkedRunId(
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  interview: HandlerDeps['interview'],
): string | null | undefined {
  if (intent?.createdRunId) return intent.createdRunId;
  return interview?.run_id;
}

export async function resolveStartTarget(
  deps: StartRecoveryDeps,
): Promise<ResolvedStartTarget> {
  const payload = buildCreateRunPayload(deps);
  const chatId = payload.interview_id;
  const intent = await readStartIntent(chatId);
  const linked = await getLinkedRun(
    linkedRunId(intent, deps.interview),
    chatId,
    intent,
    deps,
  );
  if (linked) {
    if (isCancelledStatus(linked.status)) {
      return createStartTarget(payload, chatId, undefined);
    }
    return linked;
  }
  if (intent && !sameCreatePayload(intent.payload, payload)) {
    return resolveChangedPendingIntent(payload, chatId, intent, deps);
  }
  return createStartTarget(payload, chatId, intent);
}

async function resolveChangedPendingIntent(
  payload: CreateRunPayload,
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload>,
  deps: StartRecoveryDeps,
): Promise<ResolvedStartTarget> {
  const previous = await postCreate(payload, chatId, intent);
  const settled = await cancelUnstartedDraft(previous, deps);
  if (isCancelledStatus(settled.status)) {
    return createAfterCancelledReceipt(payload, chatId, settled);
  }
  if (isStartedStatus(settled.status)) {
    return {
      ...settled,
      stage: stageForRun(deps.stageToStart, deps, settled.run, intent),
    };
  }
  restoreDraft(deps);
  throw startErrorForStatus(settled.status) ?? runOutcomeError(settled.status);
}

async function cancelUnstartedDraft(
  target: ResolvedStartTarget,
  deps: StartRecoveryDeps,
): Promise<ResolvedStartTarget> {
  if (!isDraftStatus(target.status)) return target;
  const status = await cancelAndReadStatus(target.runId);
  if (retiresStartIntent(status)) {
    return {...target, status};
  }
  restoreDraft(deps);
  throw new Error(
    'The previous setup is still unresolved. Retry after confirming its run was cancelled.',
  );
}

function sameCreatePayload(
  first: CreateRunPayload,
  second: CreateRunPayload,
): boolean {
  return JSON.stringify(first) === JSON.stringify(second);
}

function stageForRun(
  stage: SpecStage,
  deps: StartRecoveryDeps,
  run: Run,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
): SpecStage {
  const linked: LinkedRunTarget = {
    chatId: recoveryChatId(deps, intent),
    runId: run.id,
    chat: undefined,
    interview: deps.interview,
  };
  return {
    ...stage,
    spec: recoverySpecForRun(linked, run, recoveryPayload(intent)),
  };
}

function recoveryChatId(
  deps: StartRecoveryDeps,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
): string {
  return intent?.payload.interview_id ?? deps.interview?.id ?? '';
}

function recoveryPayload(
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
): PendingRunCreatePayload | undefined {
  return intent?.payload as PendingRunCreatePayload | undefined;
}

async function getLinkedRun(
  runId: string | null | undefined,
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  deps: StartRecoveryDeps,
): Promise<ResolvedStartTarget | undefined> {
  if (!runId) return undefined;
  intent = rememberLinkedRun(chatId, intent, runId);
  let linkedRun;
  try {
    linkedRun = await getRun(runId);
  } catch (error) {
    restoreDraft(deps);
    throw error;
  }
  if (retiresStartIntent(linkedRun.status)) retireIntent(chatId, intent);
  return {
    runId,
    status: linkedRun.status,
    intent,
    stage: stageForRun(deps.stageToStart, deps, linkedRun, intent),
    run: linkedRun,
  };
}

function rememberLinkedRun(
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  runId: string,
): PendingCreateIntent<CreateRunPayload> | undefined {
  if (!chatId || !intent || intent.createdRunId) return intent;
  rememberPendingCreateRun(chatId, intent.key, runId);
  return {...intent, createdRunId: runId};
}

async function createStartTarget(
  payload: CreateRunPayload,
  chatId: string | undefined,
  pending: PendingCreateIntent<CreateRunPayload> | undefined,
): Promise<ResolvedStartTarget> {
  let intent = pending;
  if (!intent && chatId) intent = await getPendingCreateIntent(chatId, payload);
  const target = await postCreate(payload, chatId, intent);
  if (isCancelledStatus(target.status)) {
    return createAfterCancelledReceipt(payload, chatId, target);
  }
  if (retiresStartIntent(target.status)) retireIntent(chatId, intent);
  return target;
}

async function createAfterCancelledReceipt(
  payload: CreateRunPayload,
  chatId: string | undefined,
  cancelled: ResolvedStartTarget,
): Promise<ResolvedStartTarget> {
  retireIntent(chatId, cancelled.intent);
  const intent = chatId
    ? await getPendingCreateIntent(chatId, payload)
    : undefined;
  const replacement = await postCreate(payload, chatId, intent);
  if (isCancelledStatus(replacement.status)) {
    retireIntent(chatId, replacement.intent);
    throw new Error(
      'The cancelled run was retired. Click Start research again.',
    );
  }
  if (retiresStartIntent(replacement.status)) {
    retireIntent(chatId, replacement.intent);
  }
  return replacement;
}

async function postCreate(
  payload: CreateRunPayload,
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
): Promise<ResolvedStartTarget> {
  let created;
  try {
    created = await sendCreate(payload, intent);
  } catch (error) {
    retireRejectedIntent(chatId, intent, error);
    throw error;
  }
  rememberCreatedRun(chatId, intent, created.id);
  return {runId: created.id, status: created.status, intent, run: created};
}

async function sendCreate(
  payload: CreateRunPayload,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
) {
  if (intent) return createRun(intent.payload, {idempotencyKey: intent.key});
  return createRun(payload);
}

function retireRejectedIntent(
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  error: unknown,
): void {
  if (chatId && intent && isDefinitiveCreateRejection(error)) {
    retireIntent(chatId, intent);
  }
}

function rememberCreatedRun(
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  runId: string,
): void {
  if (chatId && intent) rememberPendingCreateRun(chatId, intent.key, runId);
}

function isDefinitiveCreateRejection(error: unknown): boolean {
  return (
    error instanceof Error &&
    'status' in error &&
    typeof error.status === 'number' &&
    [400, 401, 403, 404, 413, 415, 422].includes(error.status)
  );
}
