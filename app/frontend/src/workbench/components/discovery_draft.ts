// The form state behind the "evolve a program" dialog, and the spec it
// becomes.
//
// Kept apart from the dialog so the rules are testable without a DOM:
// what makes a draft startable, and how its fields map onto the
// `discovery` block the API validates. The backend is the authority on
// that block -- this only has to produce one it will accept, and say so
// in the reader's terms when it cannot.

import type {DiscoverySpec} from '@/api/runs';

/** One filled-in discovery form. Every field is a string, as typed. */
export interface DiscoveryDraft {
  goal: string;
  metric: string;
  direction: 'maximize' | 'minimize';
  command: string;
  filename: string;
  program: string;
  generations: string;
  children: string;
}

// The starter program is deliberately complete and runnable rather than a
// placeholder: writing `metrics.json` is the whole contract between a
// program and the search, and a reader who has to infer it from prose
// gets it wrong on the first run.
const STARTER_PROGRAM = `import json

# Whatever this computes, report it here. The search reads this file
# after every run and optimizes the metric your objective names.
score = sum(i * i for i in range(10))

with open("metrics.json", "w") as handle:
    json.dump({"score": float(score)}, handle)
`;

/** A draft with the defaults the dialog opens on. */
export const EMPTY_DRAFT: DiscoveryDraft = {
  goal: '',
  metric: 'score',
  direction: 'maximize',
  command: 'python3 main.py',
  filename: 'main.py',
  program: STARTER_PROGRAM,
  generations: '5',
  children: '3',
};

function positiveInteger(value: string): number | null {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) return null;
  return parsed;
}

// The command as argv. Split on whitespace, never parsed as a shell
// line: nothing downstream runs a shell, so pretending quotes and pipes
// work here would produce a command that fails inside the sandbox for a
// reason nothing on this form explains.
function argv(command: string): string[] {
  return command.trim().split(/\s+/).filter(Boolean);
}

/**
 * What is wrong with a draft, in the reader's terms.
 *
 * Checked here as well as by the backend, which is the authority: a
 * round-trip to be told the metric is blank is a worse answer than the
 * form saying so, and the backend's message is written for a spec
 * rather than for these fields.
 *
 * @param draft The form as filled in.
 * @returns One sentence per problem; empty when the draft is startable.
 */
export function draftProblems(draft: DiscoveryDraft): string[] {
  const checks: [boolean, string][] = [
    [!draft.goal.trim(), 'Say what the run is for.'],
    [!draft.metric.trim(), 'Name the metric your program reports.'],
    [
      argv(draft.command).length === 0,
      'Give the command that runs the program.',
    ],
    [!draft.filename.trim(), 'Name the program file.'],
    [!draft.program.trim(), 'The program is empty.'],
    [
      positiveInteger(draft.generations) === null,
      'Generations must be a whole number, at least 1.',
    ],
    [
      positiveInteger(draft.children) === null,
      'Variants per generation must be a whole number, 1 or more.',
    ],
  ];
  return checks.filter(([failed]) => failed).map(([, message]) => message);
}

/**
 * Turns a valid draft into the `discovery` block the API takes.
 *
 * @param draft The form as filled in; call `draftProblems` first.
 * @returns The spec to send with the run.
 */
export function draftToSpec(draft: DiscoveryDraft): DiscoverySpec {
  return {
    objective: {metric: draft.metric.trim(), direction: draft.direction},
    stages: [{name: 'run', argv: argv(draft.command)}],
    seed_source: {[draft.filename.trim()]: draft.program},
    max_generations: positiveInteger(draft.generations) ?? 1,
    children_per_generation: positiveInteger(draft.children) ?? 1,
  };
}
