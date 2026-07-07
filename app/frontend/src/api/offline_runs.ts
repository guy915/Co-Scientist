import type {
  CitationRow,
  Evidence,
  Hypothesis,
  MatchRow,
  Message,
  Report,
  Review,
  Run,
  RunEvent,
  RunFocus,
  RunTier,
  RunWithSummary,
  SafetyDecision,
  SystemStatus,
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
const MESSAGE_KEY = 'coscientist-offline-messages-v1';

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

function messagesByRun(): Record<string, Message[]> {
  if (!canStore()) return {};
  const raw = window.localStorage.getItem(MESSAGE_KEY);
  if (!raw) return {};
  try {
    return JSON.parse(raw) as Record<string, Message[]>;
  } catch {
    return {};
  }
}

function writeMessages(value: Record<string, Message[]>) {
  if (!canStore()) return;
  window.localStorage.setItem(MESSAGE_KEY, JSON.stringify(value));
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

export function offlineCancelRun(id: string): {id: string; status: string} {
  const records = readStoredRecords();
  const index = records.findIndex(record => record.run.id === id);
  if (index >= 0) {
    records[index] = {
      ...records[index],
      run: {
        ...records[index].run,
        status: 'cancelled',
        updated_at: nowSeconds(),
      },
    };
    writeStoredRecords(records);
  }
  return {id, status: 'cancelled'};
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

export function offlineCitations(id: string): CitationRow[] {
  return findRecord(id)?.citations ?? [];
}

export function offlineReport(id: string): Report | null {
  return findRecord(id)?.report ?? null;
}

export function offlineSafety(id: string): SafetyDecision[] {
  return findRecord(id)?.safety ?? [];
}

export function offlineEvents(id: string): RunEvent[] {
  return findRecord(id)?.events ?? [];
}

export function offlineStatus(): SystemStatus {
  return {
    mcp_available: false,
    pubmed_available: false,
    literature_review_available: true,
    mcp_server_url: '',
    provider: 'mock',
    mock_mode: true,
    has_provider_key: false,
    engine_importable: false,
    model_name: 'offline/mock',
  };
}

export function offlineListMessages(runId: string): Message[] {
  return messagesByRun()[runId] ?? [];
}

export function offlineSendMessage(
  runId: string,
  content: string,
  kind: 'steering' | 'qa' = 'steering',
): Message {
  const all = messagesByRun();
  const list = all[runId] ?? [];
  const message: Message = {
    id: Date.now(),
    run_id: runId,
    sender: 'user',
    content,
    kind,
    created_at: Date.now() / 1000,
    applied: kind === 'steering',
    status: kind === 'steering' ? 'applied' : undefined,
  };
  all[runId] = [...list, message];
  writeMessages(all);
  return message;
}

export function offlineAnswer(runId: string, question: string): Message {
  const answer =
    `Co-Scientist is using the ranked hypotheses, reviews, and evidence for this run to answer: "${question}". ` +
    'The leading idea remains the highest-Elo hypothesis because it is the most specific and directly testable.';
  const all = messagesByRun();
  const list = all[runId] ?? [];
  const questionMessage: Message = {
    id: Date.now(),
    run_id: runId,
    sender: 'user',
    content: question,
    kind: 'qa',
    created_at: Date.now() / 1000,
    applied: false,
  };
  const message: Message = {
    id: Date.now() + 1,
    run_id: runId,
    sender: 'system',
    content: answer,
    kind: 'qa',
    created_at: Date.now() / 1000,
    applied: false,
  };
  all[runId] = [...list, questionMessage, message];
  writeMessages(all);
  return message;
}
