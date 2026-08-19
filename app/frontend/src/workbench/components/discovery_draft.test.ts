import {describe, expect, it} from 'vitest';
import {
  type DiscoveryDraft,
  draftProblems,
  draftToSpec,
  EMPTY_DRAFT,
} from './discovery_draft';

function draft(overrides: Partial<DiscoveryDraft> = {}): DiscoveryDraft {
  return {...EMPTY_DRAFT, goal: 'Find a faster sieve', ...overrides};
}

describe('draftProblems', () => {
  it('accepts the dialog defaults once a goal is typed', () => {
    // The defaults are the form a reader first sees, so anything wrong
    // with them is wrong for everyone.
    expect(draftProblems(draft())).toEqual([]);
  });

  it('names every problem at once rather than the first', () => {
    const found = draftProblems(
      draft({goal: '  ', metric: '', command: '   '}),
    );
    expect(found).toHaveLength(3);
  });

  it('refuses a budget that is not a whole number', () => {
    // Sent through, these reach the backend as a spec it accepts and a
    // run that does nothing -- 0 generations is a search of one.
    expect(draftProblems(draft({generations: '0'}))).not.toEqual([]);
    expect(draftProblems(draft({generations: '2.5'}))).not.toEqual([]);
    expect(draftProblems(draft({children: '-1'}))).not.toEqual([]);
  });
});

describe('draftToSpec', () => {
  it('splits the command into argv rather than passing a shell line', () => {
    // Nothing downstream runs a shell, so a single string would arrive
    // as one impossible executable name.
    const spec = draftToSpec(draft({command: '  python3   main.py --fast '}));
    expect(spec.stages[0].argv).toEqual(['python3', 'main.py', '--fast']);
  });

  it('files the program under the name the form gave it', () => {
    const spec = draftToSpec(draft({filename: ' solver.py ', program: 'x=1'}));
    expect(spec.seed_source).toEqual({'solver.py': 'x=1'});
  });

  it('carries the direction, since a minimized metric is stored negated', () => {
    const spec = draftToSpec(draft({metric: 'seconds', direction: 'minimize'}));
    expect(spec.objective).toEqual({metric: 'seconds', direction: 'minimize'});
  });

  it('starts from a program that already writes metrics.json', () => {
    // The contract between a program and the search. A placeholder that
    // did not write the file would make every first run score nothing.
    expect(EMPTY_DRAFT.program).toContain('metrics.json');
  });
});
