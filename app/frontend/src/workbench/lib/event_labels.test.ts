import {describe, it, expect} from 'vitest';
import {EVENT_LABELS, formatEventLabel} from './event_labels';

describe('formatEventLabel', () => {
  it('looks up canonical types in the label map', () => {
    expect(formatEventLabel('supervisor.plan')).toBe('Supervisor');
    expect(formatEventLabel('literature_review')).toBe('Literature retrieval');
    expect(formatEventLabel('generate')).toBe('Generation');
    expect(formatEventLabel('ranking')).toBe('Ranking');
    expect(formatEventLabel('meta_review')).toBe('Meta-review');
  });

  it('resolves legacy engine.-prefixed types via the fallback', () => {
    // Old persisted runs emitted engine.<node>; the prefix is stripped and the
    // canonical map is retried so historical runs still render friendly labels.
    expect(formatEventLabel('engine.generate')).toBe('Generation');
    expect(formatEventLabel('engine.ranking')).toBe('Ranking');
    expect(formatEventLabel('engine.literature_review')).toBe(
      'Literature retrieval',
    );
  });

  it('prettifies a stripped legacy type with no canonical entry', () => {
    // engine.supervisor (bare node name) has no canonical map entry.
    expect(formatEventLabel('engine.supervisor')).toBe('supervisor');
  });

  it('prettifies unknown types by replacing separators', () => {
    expect(formatEventLabel('some_unknown.type')).toBe('some unknown type');
    expect(formatEventLabel('mystery')).toBe('mystery');
  });

  it('exposes the canonical map for shared consumers', () => {
    expect(EVENT_LABELS.status).toBe('Status');
    expect(EVENT_LABELS.report).toBe('Report synthesis');
  });
});
