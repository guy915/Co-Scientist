import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  installLayoutMocks,
  logsApiMock,
  systemApiMock,
} from './layout_test_support';
import {renderLayout} from './layout_test_support';

beforeEach(() => {
  installLayoutMocks();
});

// The panel only offers Report where the server can actually send mail.
function withEmailDelivery() {
  systemApiMock.getSystemStatus.mockResolvedValue({
    llm_backend: 'real',
    provider: 'engine',
    model_name: 'test/model',
    email_notifications_available: true,
  });
}

async function openReportButton() {
  fireEvent.click(screen.getByRole('button', {name: /Logs/i}));
  const button = await screen.findByRole('button', {name: /Report/});
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

it('sends the same export the Copy button produces', async () => {
  withEmailDelivery();
  renderLayout();

  fireEvent.click(await openReportButton());

  await waitFor(() => expect(logsApiMock.reportAppLogs).toHaveBeenCalledOnce());
  // The whole self-describing document, not a pointer to it: the panel's
  // view is anchored to this browsing session, so a link would not
  // reproduce what the scientist was looking at.
  const [report] = logsApiMock.reportAppLogs.mock.calls[0] as [string];
  expect(report).toContain('=== LOGS (JSON) ===');
  expect(await screen.findByText('Sent')).toBeInTheDocument();
});

it('says so when the report could not be sent', async () => {
  withEmailDelivery();
  logsApiMock.reportAppLogs.mockRejectedValue(new Error('503'));
  renderLayout();

  fireEvent.click(await openReportButton());

  // A report that silently did not arrive is worse than no button: the
  // scientist stops looking for another way to tell anyone.
  expect(await screen.findByText("Couldn't send")).toBeInTheDocument();
});
