import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {expect, it, vi} from 'vitest';
import {ActiveRunView} from './run_detail_active';
import {makeRun} from './run_detail_test_support';
import {SupervisorAllocationLedger} from './run_detail_supervisor_plan';

const allocation = (seq: number, task_type: string, iteration: number) => ({
  id: seq,
  run_id: 'run-1',
  seq: seq - 1,
  iteration,
  task_type,
  status: 'queued',
  reason: `Observable reason ${seq}`,
  planner_reason: `Model rationale ${seq}`,
  priority: 80,
  termination_reason: null,
  created_at: 1_790_000_000,
});

it('opens as an accessible disclosure and preserves allocation order and provenance labels', async () => {
  const user = userEvent.setup();
  render(
    <ActiveRunView
      run={{...makeRun('Study pathway X'), status: 'running'}}
      events={[]}
      evidenceCount={0}
      ideaCount={0}
      allocationLedger={{
        response: {
          plan: {
            run_id: 'run-1',
            plan: {},
            orchestrator_state: {},
            decision_provenance: 'model',
            termination_reason: null,
            created_at: 1_790_000_000,
            updated_at: 1_790_000_000,
          },
          allocations: [
            allocation(1, 'generate', 1),
            allocation(2, 'rank', 1),
          ],
        },
        loading: false,
        error: null,
        onRetry: vi.fn(),
      }}
    />,
  );

  const summary = screen.getByText('Supervisor allocation ledger');
  expect(summary.tagName).toBe('SUMMARY');
  const disclosure = summary.closest('details');
  expect(disclosure).not.toBeNull();
  await user.tab();
  expect(summary).toHaveFocus();
  await user.click(summary);
  expect(disclosure).toHaveAttribute('open');

  const rows = within(disclosure!).getAllByRole('listitem');
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent('Iteration 1');
  expect(rows[0]).toHaveTextContent('Generate');
  expect(rows[0]).toHaveTextContent('Observable reason 1');
  expect(rows[0]).toHaveTextContent('Model-stated rationale');
  expect(rows[0]).toHaveTextContent('Model rationale 1');
  expect(rows[1]).toHaveTextContent('Rank');
  expect(rows[1]).toHaveTextContent('Observable reason 2');
  expect(disclosure).toHaveTextContent('Most recent decision source: model');
});

it('distinguishes loading from a successfully empty ledger', () => {
  const view = render(
    <SupervisorAllocationLedger
      response={null}
      loading={true}
      error={null}
      onRetry={vi.fn()}
    />,
  );
  expect(screen.getByRole('status')).toHaveTextContent(
    'Loading the allocation ledger',
  );

  view.rerender(
    <SupervisorAllocationLedger
      response={{plan: null, allocations: []}}
      loading={false}
      error={null}
      onRetry={vi.fn()}
    />,
  );
  expect(screen.queryByRole('status')).toBeNull();
  expect(screen.getByText('No scheduling decisions recorded yet.')).toBeInTheDocument();
});

it('offers a scoped retry when the allocation request fails', async () => {
  const user = userEvent.setup();
  const onRetry = vi.fn();
  render(
    <SupervisorAllocationLedger
      response={null}
      loading={false}
      error="404 not found"
      onRetry={onRetry}
    />,
  );

  expect(screen.getByRole('alert')).toHaveTextContent(
    'Could not load the allocation ledger.',
  );
  await user.click(
    screen.getByRole('button', {name: 'Retry loading allocations'}),
  );
  expect(onRetry).toHaveBeenCalledOnce();
});
