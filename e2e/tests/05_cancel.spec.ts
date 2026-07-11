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
test('cancels a running run and shows the cancelled state on home', async ({
  page,
  api,
}) => {
  const goal = 'Long-running cancellation probe for the browser e2e harness';

  const {id} = await api.createRun({
    research_goal: goal,
    tier: 'ultra',
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

  // Observe the terminal state in the UI: the owned run's recents card shows
  // the cancelled status chip.
  await page.goto('/');
  const card = page.getByRole('link').filter({hasText: goal}).first();
  await expect(card).toBeVisible();
  await expect(card.getByText(/status:\s*cancelled/i)).toBeVisible();
});
