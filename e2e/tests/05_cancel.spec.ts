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
// at an iteration checkpoint well before it could finish. What the card renders
// depends only on the terminal status polled below, not on how far the run
// progressed — so the assertion holds whether the cancel lands early or late.
test('cancels a running run and shows the cancelled state on home', async ({
  page,
  api,
}) => {
  const goal = 'Long-running cancellation probe for the browser e2e harness';

  const {id} = await api.createRun({
    research_goal: goal,
    tier: 'extended',
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

  // The owned run surfaces on the session-home Recents, and its card reports
  // the terminal state. Scoped to the Recents aside (rather than any link on
  // the page) so a same-goal link elsewhere cannot stand in for it, and the
  // assertions wait for the async history render rather than racing it.
  await page.goto('/');
  const recents = page.getByRole('complementary', {name: 'Recent runs'});
  const card = recents.getByRole('link').filter({hasText: goal});
  await expect(card).toBeVisible();
  await expect(card.getByText(/status:\s*cancelled/i)).toBeVisible();
});
