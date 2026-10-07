import type {
  ChatSummary,
  Hypothesis,
  InterviewQuestion,
  MatchRow,
  Run,
  RunMessage,
  RunWithSummary,
} from '@/api/runs';
import type {InferredRunSpec} from '@/shared/lib/run_spec';
import {type ChatEntry} from '@/features/chat/chat_timeline_bubble';

export function makeHypothesis(over: Partial<Hypothesis> = {}): Hypothesis {
  return {
    id: 'h1',
    run_id: 'r1',
    parent_id: null,
    generation: 0,
    category: null,
    title: 'Untitled hypothesis',
    statement: 'A statement.',
    mechanism: null,
    expected_effect: null,
    experimental_context: null,
    created_by_agent: 'generate',
    created_at: 0,
    elo_rating: 1200,
    win_count: 0,
    loss_count: 0,
    novelty_score: null,
    plausibility_score: null,
    testability_score: null,
    safety_status: null,
    status: null,
    cluster_id: null,
    ...over,
  };
}

export function makeRun(over: Partial<Run> = {}): Run {
  return {
    id: 'r1',
    research_goal: 'goal',
    profile: 'standard',
    status: 'completed',
    provider: 'engine',
    config: {},
    created_at: 0,
    updated_at: 0,
    completed_at: null,
    error: null,
    ...over,
  };
}

export function makeRunWithSummary(
  over: Partial<RunWithSummary> = {},
): RunWithSummary {
  return {
    ...makeRun(),
    summary: {events: 0, hypotheses: 0, evidence: 0, matches: 0, reviews: 0},
    ...over,
  };
}

export function makeSpec(over: Partial<InferredRunSpec> = {}): InferredRunSpec {
  return {
    goal: 'Study liver fibrosis',
    requirements: ['Req A'],
    attributes: ['Attr A'],
    criteria: ['Crit A'],
    focus: 'balance',
    tier: 'standard',
    ...over,
  };
}

export function makeMessage(over: Partial<ChatEntry> = {}): ChatEntry {
  return {
    id: 'm1',
    role: 'user',
    content: 'Hello',
    created_at: 1,
    ...over,
  };
}

export function makeMatch(id: number, over: Partial<MatchRow> = {}): MatchRow {
  return {id, ...over} as unknown as MatchRow;
}

export function makeChatSummary(over: Partial<ChatSummary> = {}): ChatSummary {
  return {
    id: 'interview-1',
    title: 'Cold-stress glucose homeostasis',
    challenge: 'Investigate glucose homeostasis.',
    status: 'completed',
    run_id: 'run-1',
    created_at: 1,
    updated_at: 3,
    ...over,
  };
}

export function makeRunMessage(over: Partial<RunMessage> = {}): RunMessage {
  return {
    id: 1,
    run_id: 'run-1',
    sender: 'user',
    content: 'Hello',
    kind: 'qa',
    created_at: 1,
    applied: false,
    meta: null,
    ...over,
  };
}

export function makeQuestion(
  over: Partial<InterviewQuestion> = {},
): InterviewQuestion {
  return {
    header: 'Model system',
    question: 'Which model system should the ideas be built around?',
    multi_select: false,
    options: [
      {label: 'Primary human cells', description: 'Closest to patient biology'},
      {label: 'iPSC-derived line', description: 'Renewable and editable'},
    ],
    ...over,
  };
}

// The export fences its JSON in Markdown; strip the fence before parsing.
export function exportedRecords<T = Record<string, unknown>>(
  text: string,
): T[] {
  const body = text.slice(text.indexOf('```json') + '```json'.length);
  return JSON.parse(body.slice(0, body.lastIndexOf('```'))) as T[];
}
