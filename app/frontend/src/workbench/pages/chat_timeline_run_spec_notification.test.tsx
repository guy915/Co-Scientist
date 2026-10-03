import {fireEvent, render, screen} from '@testing-library/react';
import {expect, test, vi} from 'vitest';
import {makeSpec} from '@/test_fixtures';
import {CompletionNotification} from './chat_timeline_run_spec_card';

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
