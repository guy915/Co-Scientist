import type {
  Evidence,
  Hypothesis,
  MatchRow,
  Report,
  Review,
  Run,
  RunEvent,
  RunFocus,
  RunTier,
  RunWithSummary,
} from './run_types';
import {
  artifactsFor,
  defaultSetup,
  demoRecords,
  nowSeconds,
  runFor,
  type OfflineRunRecord,
} from './offline_run_records';
import {makePrefixedId} from '@/lib/id';

const STORAGE_KEY = 'coscientist-offline-runs-v1';

function canStore(): boolean {
  return typeof window !== 'undefined' && Boolean(window.localStorage);
}

function readStoredRecords(): OfflineRunRecord[] {
  if (!canStore()) return [];
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return [];
  try {
    return JSON.parse(raw) as OfflineRunRecord[];
  } catch {
    return [];
  }
}

function writeStoredRecords(records: OfflineRunRecord[]) {
  if (!canStore()) return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
}

function allRecords(): OfflineRunRecord[] {
  const byId = new Map<string, OfflineRunRecord>();
  for (const record of [...readStoredRecords(), ...demoRecords()]) {
    byId.set(record.run.id, record);
  }
  return [...byId.values()].sort((a, b) => b.run.updated_at - a.run.updated_at);
}

function findRecord(id: string): OfflineRunRecord | null {
  return allRecords().find(record => record.run.id === id) ?? null;
}

function summary(record: OfflineRunRecord) {
  return {
    events: record.events.length,
    hypotheses: record.hypotheses.length,
    evidence: record.evidence.length,
    matches: record.matches.length,
    reviews: record.reviews.length,
  };
}

export function isOfflineRunId(id: string): boolean {
  return Boolean(findRecord(id));
}

export function offlineListRuns(): Run[] {
  return readStoredRecords().map(record => record.run);
}

export function offlineListDemoRuns(): Run[] {
  return demoRecords().map(record => record.run);
}

export function offlineCreateRun(input: {
  research_goal: string;
  requirements?: string[];
  attributes?: string[];
  criteria?: string[];
  focus?: RunFocus;
  tier?: RunTier;
}): Run {
  const createdAt = nowSeconds();
  const setup = {
    ...defaultSetup(input.research_goal, input.focus, input.tier),
    requirements: input.requirements?.length
      ? input.requirements
      : defaultSetup(input.research_goal).requirements,
    attributes: input.attributes?.length
      ? input.attributes
      : defaultSetup(input.research_goal).attributes,
    criteria: input.criteria?.length
      ? input.criteria
      : defaultSetup(input.research_goal).criteria,
  };
  const run = runFor(
    makePrefixedId('offline-run'),
    input.research_goal,
    createdAt,
    {setup, focus: setup.focus, tier: setup.tier},
    'draft',
  );
  const record = artifactsFor(run);
  record.hypotheses = [];
  record.evidence = [];
  record.matches = [];
  record.reviews = [];
  record.citations = [];
  record.report = null;
  record.events = [];
  writeStoredRecords([record, ...readStoredRecords()]);
  return run;
}

export function offlineStartRun(id: string): {id: string; status: string} {
  const records = readStoredRecords();
  const index = records.findIndex(record => record.run.id === id);
  if (index < 0) return {id, status: 'completed'};
  const completedAt = nowSeconds();
  const nextRun: Run = {
    ...records[index].run,
    status: 'completed',
    updated_at: completedAt,
    completed_at: completedAt,
  };
  records[index] = artifactsFor(nextRun);
  writeStoredRecords(records);
  return {id, status: 'completed'};
}

export function offlineGetRun(id: string): RunWithSummary {
  const record = findRecord(id);
  if (!record) throw new Error(`offline run not found: ${id}`);
  return {...record.run, summary: summary(record)};
}

export function offlineHypotheses(id: string): Hypothesis[] {
  return findRecord(id)?.hypotheses ?? [];
}

export function offlineEvidence(id: string): Evidence[] {
  return findRecord(id)?.evidence ?? [];
}

export function offlineMatches(id: string): MatchRow[] {
  return findRecord(id)?.matches ?? [];
}

export function offlineReviews(id: string): Review[] {
  return findRecord(id)?.reviews ?? [];
}

export function offlineReport(id: string): Report | null {
  return findRecord(id)?.report ?? null;
}

export function offlineEvents(id: string): RunEvent[] {
  return findRecord(id)?.events ?? [];
}
