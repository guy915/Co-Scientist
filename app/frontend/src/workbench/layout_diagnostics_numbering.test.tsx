import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';

beforeEach(() => installLayoutMocks());

it('renumbers shown records consecutively, ignoring id gaps', async () => {
  // Store ids are global and include filtered-out noise, so a
  // filtered view has holes (#12, #13, #30, #31) that read as failed
  // renders. The panel numbers what it shows instead.
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [12, 13, 30, 31].map(id => ({
      id,
      created_at: 1_700_000_000 + id,
      level: 'INFO',
      levelno: 20,
      logger: 'app.main',
      message: `record ${id}`,
      run_id: null,
      exc_text: null,
    })),
    last_id: 33,
    total: 4,
    session_total: 4,
  });
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 4/i}));
  await screen.findByText(/record 12/);

  const numbers = Array.from(
    document.querySelectorAll('.ucs-diagnostic-entry-meta'),
  ).map(el => el.querySelector('span')?.textContent);
  expect(numbers).toEqual(['#1', '#2', '#3', '#4']);
  // The badge is the newest row's number, so header and list agree.
  expect(await screen.findByText('Total 4')).toBeInTheDocument();
  expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(0, 100);
});

it('numbers a capped window by position in the stream', async () => {
  // 250 records match the filter but only the newest 100 are fetched:
  // those are records 151..250, not 1..100.
  const logs = Array.from({length: 100}, (_, index) => ({
    id: 1000 + index * 3,
    created_at: 1_700_000_000 + index,
    level: 'INFO',
    levelno: 20,
    logger: 'app.main',
    message: `record ${index}`,
    run_id: null,
    exc_text: null,
  }));
  logsApiMock.getAppLogs.mockResolvedValue({
    logs,
    last_id: 5000,
    total: 250,
    session_total: 250,
  });
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 250/i}));
  await screen.findByText(/record 99/);

  const metas = document.querySelectorAll('.ucs-diagnostic-entry-meta');
  expect(metas[0].querySelector('span')?.textContent).toBe('#151');
  expect(metas[99].querySelector('span')?.textContent).toBe('#250');
});

it('never shows more than the 100 newest records', async () => {
  // The fetch already asks for 100, but the panel enforces the cap
  // itself too: even an oversized payload renders as the newest 100.
  const many = Array.from({length: 120}, (_, index) => ({
    id: index + 1,
    created_at: 1_700_000_000 + index,
    level: 'INFO',
    levelno: 20,
    logger: 'app.main',
    message: `record ${index + 1}`,
    run_id: null,
    exc_text: null,
  }));
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: many,
    last_id: 120,
    total: 120,
    session_total: 120,
  });
  const {container} = renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 120/i}));
  await screen.findByText(/record 120/);

  const entries = container.querySelectorAll('.ucs-diagnostic-entry');
  expect(entries).toHaveLength(100);
  // The newest 100 (21..120), not the oldest.
  expect(screen.queryByText(/record 20$/)).toBeNull();
  expect(entries[0].textContent).toContain('#21');
});
