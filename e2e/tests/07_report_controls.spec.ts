import {expect, test} from '../support/fixtures';

test('Goal Report supports follow-up, download, sharing, and revocation', async ({
  page,
  context,
  api,
}) => {
  const researchGoal = 'Which pathway best restores synaptic ATP after ischemia?';
  const {id: runId} = await api.createRun({
    research_goal: researchGoal,
    tier: 'standard',
  });
  await api.startRun(runId);
  await expect
    .poll(async () => (await api.getRun(runId)).status)
    .toBe('completed');
  await page.goto(`/runs/${runId}/ideas`);

  await expect(page.getByRole('button', {name: 'Open Agent'})).toBeVisible();
  await page.getByRole('button', {name: 'Open Agent'}).click();
  await expect(page.getByRole('dialog', {name: 'Open Agent'})).toBeVisible();
  await page.getByRole('button', {name: 'Close Agent'}).click();

  await expect(page.getByRole('button', {name: 'Open in NotebookLM'})).toBeVisible();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', {name: 'Download'}).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.md$/);

  await page.getByRole('button', {name: 'Share'}).click();
  await page.getByRole('button', {name: 'Create and copy link'}).click();
  const publicLink = page.getByRole('textbox', {name: 'Public link'});
  await expect(publicLink).toBeVisible();
  const sharedUrl = await publicLink.inputValue();

  const sharedPage = await context.newPage();
  await sharedPage.goto(sharedUrl);
  await expect(
    sharedPage.getByRole('heading', {name: researchGoal}),
  ).toBeVisible();
  await expect(sharedPage.getByText('Agent Insights')).toBeVisible();

  await page.getByRole('button', {name: 'Revoke public link'}).click();
  await expect(page.getByRole('status')).toHaveText('Public access revoked');
  await sharedPage.reload();
  await expect(sharedPage.getByRole('alert')).toContainText(
    /shared Goal Report is unavailable/i,
  );
});
