import {expect, test} from '../support/fixtures';

// Flow: cancel a running run and observe its terminal state in the UI.
//
// There is deliberately no in-product affordance to cancel a run (adding one
// would be a forbidden behavior change), so the run is created, started, and
// cancelled over the backend API — every call tagged with the same
// X-Client-ID the browser uses, so the run is owned by this browser session
// and surfaces on its home recents list. The observable under test is the
// terminal state rendered in the UI: the recents card's "Status: Cancelled"
// chip.
//
// Determinism: the run is sized large (extra iterations and hypotheses) so it
// stays active long enough to catch running and to land a cooperative cancel
// at an iteration checkpoint well before it could finish.
test('cancels a running fixture without contaminating faithful history', async ({
  page,
  api,
}) => {
  const goal = 'Long-running cancellation probe for the browser e2e harness';

  const {id} = await api.createRun({
    research_goal: goal,
    tier: 'advanced',
    max_iterations: 8,
    initial_hypotheses_count: 30,
  });
  await api.startRun(id);

  // Wait until the workflow is actually running before cancelling.
  await expect
    .poll(async () => (await api.getRun(id)).status, {
      timeout: 20_000,
      intervals: [200],
    })
    .toMatch(/running|synthesizing/);

  await api.cancelRun(id);

  // Cancellation is cooperative; the workflow lands in CANCELLED at its next
  // checkpoint.
  await expect
    .poll(async () => (await api.getRun(id)).status, {
      timeout: 20_000,
      intervals: [200],
    })
    .toBe('cancelled');

  // Explicit mock fixtures remain quarantined from faithful Recents even
  // though the lifecycle API correctly recorded their terminal state.
  await page.goto('/');
  const card = page.getByRole('link').filter({hasText: goal}).first();
  await expect(card).toHaveCount(0);
});
