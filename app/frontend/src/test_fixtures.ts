/** Shared factories for building typed API objects in tests. */
import type {Hypothesis, MatchRow, Run} from '@/api/runs';
import type {InferredRunSpec} from '@/workbench/run_spec';
import {type ChatEntry} from '@/workbench/pages/chat_timeline_bubble';

/**
 * A fully-populated Hypothesis; override only the fields a test cares
 * about.
 */
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

/**
 * A minimal run record carrying the always-present fields; override only
 * what a test needs. Optional signals (latest_stage, execution_progress,
 * summary, ...) are supplied through `over`.
 */
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
  } as Run;
}

/** An inferred run specification with every section populated. */
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

/** A chat timeline entry; defaults to a short user message. */
export function makeMessage(over: Partial<ChatEntry> = {}): ChatEntry {
  return {
    id: 'm1',
    role: 'user',
    content: 'Hello',
    created_at: 1,
    ...over,
  };
}

/** A tournament match row keyed by `id`; override any extra fields. */
export function makeMatch(id: number, over: Partial<MatchRow> = {}): MatchRow {
  return {id, ...over} as unknown as MatchRow;
}
