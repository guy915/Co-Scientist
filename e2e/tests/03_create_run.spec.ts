import {expect, test} from '../support/fixtures';

// Flow: create a run from the chat workspace, start it, watch the live
// pipeline drive the run-detail surface over SSE, and see it complete.
//
// The run is created and started entirely through the UI (composer -> draft
// spec card -> Start research -> started card). Opening the run detail mounts
// the SSE subscription; the Ideas and Overview tabs then populate only because
// streamed pipeline events (generate/ranking/report) drove the refetches, so
// asserting on the Elo-ranked hypotheses and the synthesized report is a
// genuine observation of the streamed run reaching completion.
test('creates a run from chat, starts it, and watches it complete', async ({
  page,
}) => {
  await page.goto('/');

  const goal =
    'What molecular checkpoints govern ferroptosis escape in glioblastoma stem cells?';
  const composer = page.getByRole('textbox');
  await composer.click();
  await composer.fill(goal);
  await composer.press('Enter');

  // The submitted goal is inferred into an editable draft run spec.
  const startButton = page.getByRole('button', {name: 'Start research'});
  await expect(startButton).toBeVisible();
  await expect(page.getByText(goal).first()).toBeVisible();

  // Start the run: createRun + startRun round-trip, then the terminal
  // "started" card.
  await startButton.click();
  await expect(
    page.getByText(/your session has been started/i),
  ).toBeVisible();

  // Open the run detail. Capture the SSE stream opening (browser -> backend)
  // as direct evidence the live event channel was established.
  const ssePromise = page.waitForResponse(
    response => /\/api\/runs\/[^/]+\/events/.test(response.url()),
    {timeout: 30_000},
  );
  await page.getByRole('button', {name: /view session details/i}).click();
  const sse = await ssePromise;
  expect(sse.status()).toBe(200);
  await expect(page).toHaveURL(/\/runs\/[^/]+\/details/);

  // Ideas tab: hypotheses arrive with Elo ratings (generate + ranking events).
  await page.getByRole('button', {name: 'All Ideas'}).click();
  await expect(page.getByText(/elo rating:/i).first()).toBeVisible();

  // Overview tab: the synthesized report lands near the end of the pipeline.
  // "Specific aims" is present only once the persisted report exists, so it is
  // a clean signal that the streamed run finished and synthesized its report.
  await page.getByRole('button', {name: 'Research Overview'}).click();
  await expect(
    page.getByRole('heading', {name: /specific aims/i}),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', {name: /winning ideas/i}),
  ).toBeVisible();
});
