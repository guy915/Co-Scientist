import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  apiMock,
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';
import {logRecord} from './layout_diagnostics_test_support';

beforeEach(() => installLayoutMocks());

it('opens the diagnostics panel with dark-mode shell styling', () => {
  const {container} = renderLayout();

  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(document.documentElement).toHaveClass('dark');

  const logsButton = screen.getByRole('button', {name: /Logs 0/i});
  expect(logsButton.className).toContain('bg-cosci-logs-accent-bg');

  fireEvent.click(logsButton);

  const logsPopover = container.querySelector('.ucs-popover--logs');
  expect(logsPopover?.className).toContain('!bg-cosci-logs-surface');
  expect(screen.getByText('Diagnostic Logs')).toBeInTheDocument();
});

it('shows the same app-wide log on a run route as on home', async () => {
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [
      {
        id: 41,
        created_at: 1_700_000_000,
        level: 'INFO',
        levelno: 20,
        logger: 'app.main',
        message: 'server started',
        run_id: null,
        exc_text: null,
      },
    ],
    last_id: 41,
    total: 1,
    session_total: 1,
  });
  renderLayout('/runs/demo-ferroptosis/ideas');

  fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));

  // Entering a run subpage must not swap the log for a run-scoped view:
  // the panel is the app-wide stream everywhere.
  expect(await screen.findByText(/server started/)).toBeInTheDocument();
  expect(screen.getByText('#1')).toBeInTheDocument();
  expect(apiMock.getRunEvents).not.toHaveBeenCalled();
});

it('loads persisted backend logs into the diagnostics popover', async () => {
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [
      logRecord(3, {
        level: 'ERROR',
        levelno: 40,
        logger: 'app.engine_adapter',
        message: 'workflow exploded',
      }),
      logRecord(4, {
        logger: 'app.runs',
        message: 'run started',
        run_id: 'run-12345678',
      }),
      logRecord(5, {
        level: 'WARNING',
        levelno: 30,
        logger: 'app.diagnostics',
        message: 'mcp probe unreachable',
      }),
    ],
    last_id: 5,
    total: 3,
    session_total: 3,
  });
  renderLayout('/');

  fireEvent.click(screen.getByRole('button', {name: /Logs 0/i}));

  // The popover fetches the app-wide persisted log on open, even with no
  // run in scope (that is the point: capture is app-wide).
  await waitFor(() => expect(logsApiMock.getAppLogs).toHaveBeenCalled());
  expect(await screen.findByText('app.engine_adapter:')).toBeInTheDocument();
  expect(screen.getByText(/workflow exploded/)).toBeInTheDocument();
  // Records with no run id are attributed to the server itself.
  expect(screen.getAllByText('Server')).toHaveLength(2);
  expect(screen.getByText('Run run-1234')).toBeInTheDocument();
  // The chips split the levels the way the rows print them: WARNING is its
  // own band, not folded into Errors, so a run that only warned does not
  // read as a run that failed.
  expect(screen.getByText('Errors 1')).toBeInTheDocument();
  expect(screen.getByText('Warnings 1')).toBeInTheDocument();
  expect(screen.getByText('Info 1')).toBeInTheDocument();
  // The two server records remain in the list, but the Runs chip reflects
  // only the one record that belongs to a real research run.
  expect(screen.getByText('Runs 1')).toBeInTheDocument();

  // Clear drops only session entries; persisted backend logs remain.
  fireEvent.click(screen.getByRole('button', {name: 'Clear'}));
  expect(screen.getByText(/workflow exploded/)).toBeInTheDocument();
});

it('never scrolls sideways, even with a long logger name', async () => {
  // A long dotted logger name in the stage column used to widen the meta
  // grid past the panel and add a horizontal scrollbar. The list clips the
  // x-axis and the stage cell truncates, so only the y-axis can scroll.
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [
      logRecord(1, {
        logger:
          'co_scientist.agents.generation.literature_review.search_support',
        message: 'a very long line that would otherwise widen the panel body',
      }),
    ],
    last_id: 1,
    total: 1,
    session_total: 1,
  });
  const {container} = renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));
  await screen.findByText(/widen the panel body/);

  const list = container.querySelector('.ucs-diagnostic-list');
  expect(list?.className).toContain('overflow-x-hidden');
  expect(list?.className).not.toContain('overflow-auto');
  const stage = container.querySelector('.ucs-diagnostic-entry-meta strong');
  expect(stage?.className).toContain('truncate');
});

it('renders the message as plain text with a level meta row', async () => {
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [
      logRecord(1, {message: 'a long message that must wrap freely'}),
      logRecord(2, {
        level: 'ERROR',
        levelno: 40,
        logger: 'app.engine_adapter',
        message: 'workflow exploded',
        exc_text: 'Traceback: boom',
      }),
    ],
    last_id: 2,
    total: 2,
    session_total: 2,
  });
  const {container} = renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));
  await screen.findByText(/wrap freely/);

  const blocks = container.querySelectorAll('.ucs-diagnostic-entry pre');
  expect(blocks).toHaveLength(2);
  // No JSON scaffolding: the block is the message itself, and a
  // traceback follows on its own lines.
  expect(blocks[0].textContent).toBe('a long message that must wrap freely');
  expect(blocks[1].textContent).toBe('workflow exploded\n\nTraceback: boom');
  // The level moved to the meta row instead of a payload field.
  expect(screen.getByText('INFO')).toBeInTheDocument();
  expect(screen.getByText('ERROR')).toBeInTheDocument();
  // The block grows with its content: text wraps, nothing scrolls.
  expect(blocks[0].className).toContain('whitespace-pre-wrap');
  expect(blocks[0].className).not.toContain('overflow-auto');
  expect(blocks[0].className).not.toContain('max-h');
});
