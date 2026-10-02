import type {ReactNode} from 'react';
import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {Link, MemoryRouter} from 'react-router-dom';
import {expect, it, vi} from 'vitest';
import {WorkbenchApp} from './workbench_app';

const imports = vi.hoisted(() => ({run: 0, shared: 0, access: 0}));
const accessDownload = vi.hoisted(() => {
  let release!: () => void;
  const ready = new Promise<void>(resolve => {
    release = resolve;
  });
  return {ready, release};
});

vi.mock('../lib/ui_logging', () => ({logUiError: vi.fn()}));

vi.mock('./pages/run_detail', () => {
  imports.run += 1;
  return {RunDetail: () => <p>Run details</p>};
});
vi.mock('./pages/shared_goal_report', () => {
  imports.shared += 1;
  throw new Error('The shared page chunk could not be downloaded');
});
vi.mock('./pages/researcher_access', async () => {
  imports.access += 1;
  await accessDownload.ready;
  return {ResearcherAccessPage: () => <p>Researcher access</p>};
});
vi.mock('./pages/chat_workspace', () => ({
  ChatWorkspace: () => <p>Chat home</p>,
}));
vi.mock('./layout', () => ({
  Layout: ({children}: {children: ReactNode}) => (
    <>
      <p>Persistent shell</p>
      <Link to="/access">Open access</Link>
      <Link to="/shared/test-token">Open shared report</Link>
      {children}
    </>
  ),
}));
vi.mock('./theme_context', () => ({
  ThemeProvider: ({children}: {children: ReactNode}) => children,
}));
vi.mock('./hooks/system_status_context', () => ({
  SystemStatusProvider: ({children}: {children: ReactNode}) => children,
}));
vi.mock('./hooks/run_history_context', () => ({
  RunHistoryProvider: ({children}: {children: ReactNode}) => children,
}));
vi.mock('./hooks/chat_history_context', () => ({
  ChatHistoryProvider: ({children}: {children: ReactNode}) => children,
}));

it('opens home without importing report/access pages, then loads the selected route', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const home = render(
    <MemoryRouter initialEntries={['/']}>
      <WorkbenchApp />
    </MemoryRouter>,
  );
  const shell = screen.getByText('Persistent shell');
  expect(screen.getByText('Chat home')).toBeVisible();
  expect(imports).toEqual({run: 0, shared: 0, access: 0});

  fireEvent.click(screen.getByRole('link', {name: 'Open access'}));
  await waitFor(() => expect(imports.access).toBe(1));
  expect(screen.getByText('Chat home')).toBeVisible();
  expect(screen.getByText('Persistent shell')).toBe(shell);
  home.unmount();

  render(
    <MemoryRouter initialEntries={['/access']}>
      <WorkbenchApp />
    </MemoryRouter>,
  );
  const accessShell = screen.getByText('Persistent shell');
  expect(screen.getByRole('status')).toHaveTextContent('Loading page…');
  await act(async () => accessDownload.release());
  expect(await screen.findByText('Researcher access')).toBeVisible();
  expect(imports).toEqual({run: 0, shared: 0, access: 1});
  expect(screen.getByText('Persistent shell')).toBe(accessShell);

  fireEvent.click(screen.getByRole('link', {name: 'Open shared report'}));
  expect(await screen.findByText('Something went wrong')).toBeVisible();
  expect(screen.getByRole('button', {name: 'Reload Page'})).toBeEnabled();
  expect(imports).toEqual({run: 0, shared: 1, access: 1});
  vi.restoreAllMocks();
});
