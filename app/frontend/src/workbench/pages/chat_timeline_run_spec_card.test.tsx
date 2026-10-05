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

test.each([
  ['a valid address turns notification on', 'scientist@example.com', true],
  [
    'an invalid address stays not-yet-valid rather than off',
    'not-an-address',
    false,
  ],
  ['a blank field is a silent no-email, not an error', '', false],
])('%s', (_name, typed, enabled) => {
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
    {target: {value: typed}},
  );

  expect(onChange).toHaveBeenCalledWith(enabled, typed);
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

// Real completing interview turns restate plan fields in structured prose.

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

  expect(lead).toContain('## Scope finalized');
  expect(lead).toContain('I have incorporated the epigenetic preference');
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
