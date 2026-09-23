import {createCompletedRun, expect, test} from '../support/fixtures';

test('completed research keeps its decisions and match history inspectable', async ({
  page,
  api,
}) => {
  const id = await createCompletedRun(api, {
    research_goal: 'Offline audit of a public enzyme-stability hypothesis',
    tier: 'standard',
  });

  await page.route('**/api/runs/*/supervisor-plan', async route => {
    await new Promise(resolve => setTimeout(resolve, 1000));
    await route.continue();
  });
  await page.goto(`/runs/${id}/specifications`);
  const ledger = page.locator('details[aria-label="Supervisor allocation ledger"]');
  await expect(ledger).toBeVisible();
  await ledger.locator('summary').click();
  await expect(ledger.getByRole('status')).toContainText('Loading');
  await expect(ledger.getByText(/Decision 1/)).toBeVisible();

  await page.unroute('**/api/runs/*/supervisor-plan');
  await page.reload();
  await ledger.locator('summary').click();
  await expect(ledger.getByText(/Decision 1/)).toBeVisible();

  await page.route('**/api/runs/*/supervisor-plan', route => route.abort());
  await page.reload();
  await ledger.locator('summary').click();
  await expect(ledger.getByRole('alert')).toContainText(
    'Could not load the allocation ledger',
  );
  await expect(
    page.getByRole('heading', {name: /run specifications/i}),
  ).toBeVisible();
  await page.unroute('**/api/runs/*/supervisor-plan');
  await ledger.getByRole('button', {name: 'Retry loading allocations'}).click();
  await expect(ledger.getByText(/Decision 1/)).toBeVisible();

  await page.getByRole('link', {name: 'All Ideas', exact: true}).click();
  await expect(page.getByRole('heading', {name: 'Match history'})).toBeVisible();
  await expect(page.getByText('Elo change:', {exact: true}).first()).toBeVisible();
});
