import {isActiveStatus, isCompletedStatus, type Run} from '@/api/runs';
import {formatDurationPhrase} from '@/lib/duration';
import {capitalizeTerm} from '@/lib/text';

const HOME_RUN_DATE_FMT = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
});

export function formatHomeRunDate(timestamp: number): string {
  return HOME_RUN_DATE_FMT.format(new Date(timestamp * 1000));
}

export function formatHomeRunTimeChip(run: Run, nowSeconds: number): string {
  if (isCompletedStatus(run.status)) {
    const endTime = run.completed_at ?? run.updated_at;
    const duration = endTime ? endTime - run.created_at : -1;
    return `Total time: ${duration < 0 ? capitalizeTerm(run.status) : formatDurationPhrase(duration, {subMinute: true})}`;
  }
  if (isActiveStatus(run.status)) {
    return `Time elapsed: ${formatDurationPhrase(Math.max(0, nowSeconds - run.created_at), {subMinute: true})}`;
  }
  return `Status: ${capitalizeTerm(run.status)}`;
}

// Both leased tasks and stage events name the same work. Routing between
// agents has no phase; after tournament, the remaining work stays at step 4.
const TASK_PHASE: Record<string, number | null> = {
  bootstrap: 1,
  supervisor: 1,
  orchestrator: null,
  generate: 2,
  generation: 2,
  literature_review: 2,
  reflection: 3,
  comprehensive_reflection: 3,
  review: 3,
  verification: 3,
  deep_verification: 3,
  safety_screen: 3,
  ranking: 4,
  proximity: 4,
  evolve: 4,
  meta_review: 4,
  research_overview: 4,
  finalize: 4,
};

const STAGE_TYPES = new Set([
  'supervisor.plan',
  'literature_review',
  'generate',
  'reflection',
  'proximity',
  'ranking',
  'evolve',
  'meta_review',
  'deep_verification',
  'research_overview',
]);

/** The current 1–4 phase, or null between tasks; later cycles may go backward. */
export function homeRunStepIndex(run: Run): number | null {
  if (run.status === 'queued') return 1;
  if (run.status === 'synthesizing') return 4;
  const task = run.execution_progress?.active_task;
  if (task) {
    const [, first = '', second = ''] = task.split('.');
    const phase =
      TASK_PHASE[first === 'node' || first === 'fanout' ? second : first] ??
      null;
    if (phase !== null) return phase;
  }
  const stage = run.latest_stage;
  if (!stage || !STAGE_TYPES.has(stage)) return null;
  return TASK_PHASE[stage === 'supervisor.plan' ? 'supervisor' : stage] ?? null;
}
