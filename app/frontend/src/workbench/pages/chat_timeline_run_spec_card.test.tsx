import {fireEvent, render, screen} from '@testing-library/react';
import {expect, it, test, vi} from 'vitest';
import {makeSpec} from '@/test_fixtures';
import {
  CompletionNotification,
  planLeadIn,
} from './chat_timeline_run_spec_card';

const statusState = vi.hoisted(() => ({
  status: {email_notifications_available: true},
  unreachable: false,
}));

vi.mock('../hooks/system_status_context', () => ({
  useSystemStatus: () => statusState,
}));

test('the email field is present with no checkbox to reveal it', () => {
  render(
    <CompletionNotification
      spec={makeSpec()}
      disabled={false}
      onChange={vi.fn()}
    />,
  );
  expect(screen.queryByRole('checkbox')).toBeNull();
  expect(
    screen.getByRole('textbox', {name: /goal report is ready/i}),
  ).toBeTruthy();
});

test('a valid address turns notification on', () => {
  const onChange = vi.fn();
  render(
    <CompletionNotification
      spec={makeSpec()}
      disabled={false}
      onChange={onChange}
    />,
  );
  fireEvent.change(
    screen.getByRole('textbox', {name: /goal report is ready/i}),
    {
      target: {value: 'scientist@example.com'},
    },
  );
  expect(onChange).toHaveBeenCalledWith(true, 'scientist@example.com');
});

test('an invalid address stays not-yet-valid rather than off', () => {
  const onChange = vi.fn();
  render(
    <CompletionNotification
      spec={makeSpec()}
      disabled={false}
      onChange={onChange}
    />,
  );
  fireEvent.change(
    screen.getByRole('textbox', {name: /goal report is ready/i}),
    {
      target: {value: 'not-an-address'},
    },
  );
  expect(onChange).toHaveBeenCalledWith(false, 'not-an-address');
});

test('a blank field is a silent no-email, not an error', () => {
  const onChange = vi.fn();
  render(
    <CompletionNotification
      spec={makeSpec({notifyOnCompletion: true, completionEmail: 'partial'})}
      disabled={false}
      onChange={onChange}
    />,
  );
  fireEvent.change(
    screen.getByRole('textbox', {name: /goal report is ready/i}),
    {
      target: {value: ''},
    },
  );
  expect(onChange).toHaveBeenCalledWith(false, '');
  expect(screen.queryByText(/not configured/i)).toBeNull();
});

test('an unconfigured server keeps the field inert and says so', () => {
  statusState.status.email_notifications_available = false;
  render(
    <CompletionNotification
      spec={makeSpec()}
      disabled={false}
      onChange={vi.fn()}
    />,
  );
  expect(
    screen.getByRole('textbox', {name: /goal report is ready/i}),
  ).toBeDisabled();
  expect(screen.getByText(/not configured on this server/i)).toBeTruthy();
  statusState.status.email_notifications_available = true;
});

// Real completing turns, copied out of the interview store. The interview
// prompt asks the model to "present the finalized scope as a structured
// summary" with a heading per part, so every completing turn restates the
// five fields the plan document below it already renders as editable
// values. These fixtures are what that actually looks like.

const WITH_LEAD_IN = [
  '## Scope finalized',
  '',
  'I have incorporated the epigenetic preference and the testability',
  'requirement.',
  '',
  '### Research Challenge',
  'How can epigenetic mechanisms deactivate hepatic stellate cells?',
  '',
  '### Focus Area',
  '- Epigenetic mechanisms of hepatic stellate cell deactivation',
  '',
  '### Title',
  'Epigenetic HSC deactivation for reversal of MASH fibrosis',
  '',
  'This scope is ready to start, or it can be refined further before the run.',
].join('\n');

const SUMMARY_ONLY = [
  '## Research challenge',
  'Identify the **tumor cell-intrinsic mechanisms** of resistance.',
  '',
  '---',
  '',
  '## Lab constraints',
  '- **Patient-derived organoids** are the available experimental model.',
  '',
  'This captures the essential scope. The run can now be started.',
].join('\n');

const WITH_TABLE = [
  '## Preferences',
  '',
  '| Preference | What it means |',
  '| --- | --- |',
  '| Novel targets | Avoid the most studied candidates |',
  '',
  '## Lab constraints',
  '',
  '| Constraint | Detail |',
  '| --- | --- |',
  '| No animal work | The laboratory cannot perform in vivo experiments |',
  '',
  'If the scope above matches what you need, the run can begin.',
].join('\n');

it('drops the sections that restate the plan document own fields', () => {
  const lead = planLeadIn(WITH_LEAD_IN);

  expect(lead).not.toContain('Research Challenge');
  expect(lead).not.toContain('hepatic stellate cells?');
  expect(lead).not.toContain('Focus Area');
  expect(lead).not.toContain('Epigenetic HSC deactivation for reversal');
});

it('keeps the prose the model wrote around the summary', () => {
  const lead = planLeadIn(WITH_LEAD_IN);

  // The model's own heading and its lead-in paragraph are not a plan field,
  // so they survive...
  expect(lead).toContain('## Scope finalized');
  expect(lead).toContain('I have incorporated the epigenetic preference');
  // ...and so does the sign-off that closes the turn, even though it sits
  // inside the last dropped section.
  expect(lead).toContain('This scope is ready to start');
});

it('keeps the sign-off when the turn is nothing but the summary', () => {
  expect(planLeadIn(SUMMARY_ONLY)).toBe(
    'This captures the essential scope. The run can now be started.',
  );
});

it('drops a summary laid out as tables, rules and all', () => {
  const lead = planLeadIn(WITH_TABLE);

  expect(lead).toBe(
    'If the scope above matches what you need, the run can begin.',
  );
});

it('leaves a turn carrying no summary untouched', () => {
  const plain = 'Everything is captured. Start whenever you are ready.';
  expect(planLeadIn(plain)).toBe(plain);
});

it('is empty for a turn with nothing left to say', () => {
  expect(planLeadIn(undefined)).toBe('');
  expect(planLeadIn('   ')).toBe('');
});

it('matches a field heading carrying a parenthetical', () => {
  // Straight out of a live turn: the model headed its title section
  // "Title (proposed)", which is the plan's title section by another name.
  const turn = [
    'Here it is, laid out.',
    '',
    '## Title (proposed)',
    'Adaptive resistance to KRAS G12C inhibitors',
    '',
    'Start the run whenever you are ready.',
  ].join('\n');

  expect(planLeadIn(turn)).toBe(
    'Here it is, laid out.\n\nStart the run whenever you are ready.',
  );
});
