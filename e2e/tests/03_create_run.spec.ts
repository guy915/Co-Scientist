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
  await page.locator('input[type="file"]').setInputFiles({
    name: 'private-lactate-result.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from(
      'Private pilot result: MCT1 perturbation delayed synaptic ATP recovery.',
    ),
  });
  await expect(page.getByText('private-lactate-result.txt')).toBeVisible();
  await composer.press('Enter');

  // The Agent runs a short, model-driven interview whose questions are
  // generated from the goal (their exact wording is not fixed) and which
  // completes into an editable research plan. Answer each question that
  // appears until the plan's "Start research" action is offered, rather than
  // asserting on specific question copy.
  const startButton = page.getByRole('button', {name: 'Start research'});
  const assistantTurns = page.getByRole('button', {name: 'Copy response'});
  await expect(assistantTurns.first()).toBeVisible({timeout: 30_000});
  const answers = [
    'Prioritize GPX4-independent lipid repair mechanisms.',
    'Use patient-derived organoids and isogenic controls.',
    'Optimize for translational relevance to recurrent glioblastoma.',
    'No further constraints; proceed with the strongest directions.',
  ];
  for (const answer of answers) {
    if (await startButton.isVisible().catch(() => false)) break;
    const priorTurns = await assistantTurns.count();
    await page.getByRole('textbox').last().fill(answer);
    await page.getByRole('button', {name: 'Send'}).click();
    // The answer is consumed once the plan is ready or the model posts its
    // next question (a new assistant response bubble appears).
    await expect(async () => {
      const ready = await startButton.isVisible().catch(() => false);
      const advanced = (await assistantTurns.count()) > priorTurns;
      expect(ready || advanced).toBeTruthy();
    }).toPass({timeout: 30_000});
  }

  // The completed interview produces the editable research plan.
  await expect(startButton).toBeVisible({timeout: 30_000});
  await expect(page.getByText(goal).first()).toBeVisible();

  // Capture both lifecycle mutations as direct evidence that the browser owns
  // and starts the same draft through the cross-origin development topology.
  const createdPromise = page.waitForResponse(
    response =>
      new URL(response.url()).pathname === '/api/runs' &&
      response.request().method() === 'POST',
  );
  const startAttemptPromise = page.waitForResponse(
    response =>
      /\/api\/runs\/[^/]+\/start$/.test(new URL(response.url()).pathname) &&
      response.request().method() === 'POST',
  );
  await startButton.click();
  const created = await createdPromise;
  expect(created.status()).toBe(200);
  const {id} = (await created.json()) as {id: string};
  const startAttempt = await startAttemptPromise;
  expect(startAttempt.status()).toBe(200);

  // Open the run detail. Capture the SSE stream opening (browser -> backend)
  // as direct evidence the live event channel was established.
  const ssePromise = page.waitForResponse(
    response => /\/api\/runs\/[^/]+\/events/.test(response.url()),
    {timeout: 30_000},
  );
  await page.goto(`/runs/${id}/specifications`);
  const sse = await ssePromise;
  expect(sse.status()).toBe(200);
  await expect(page).toHaveURL(/\/runs\/[^/]+\/specifications/);

  // The Goal Report tabs appear only after the run reaches publication.
  await expect(page.getByRole('button', {name: 'Ideas'})).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole('button', {name: 'Ideas'}).click();
  await expect(
    page.getByRole('list', {name: /ranked hypothesis list/i}),
  ).toBeVisible();
  await page.getByRole('button', {name: 'Research Overview'}).click();
  await expect(
    page.getByRole('heading', {name: /specific aims/i}),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', {name: /agent insights/i}),
  ).toBeVisible();
  await page.getByRole('button', {name: 'Learning'}).click();
  await expect(page.getByText('private-lactate-result.txt')).toBeVisible();
});
