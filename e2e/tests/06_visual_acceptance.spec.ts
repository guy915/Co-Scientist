import {fileURLToPath} from 'node:url';

import {expect, test} from '../support/fixtures';

function assetPath(name: string): string {
  return fileURLToPath(new URL(`../../docs/assets/${name}`, import.meta.url));
}

test('faithful home renders at the required desktop viewport', async ({page}) => {
  await page.setViewportSize({width: 1440, height: 720});
  await page.goto('/');

  await expect(
    page.getByRole('heading', {name: "What's your research challenge?"}),
  ).toBeVisible();
  await expect(page.locator('.reference-home-main')).toHaveCSS('opacity', '1');
  await expect(page.getByRole('button', {name: /Logs/i})).toHaveCount(0);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBe(1440);
  await page.screenshot({
    path: assetPath('faithful-home-desktop-2026-07-13.png'),
    fullPage: false,
  });
});

test('faithful home renders at the required mobile viewport', async ({page}) => {
  await page.setViewportSize({width: 390, height: 780});
  await page.goto('/');

  await expect(
    page.getByRole('heading', {name: "What's your research challenge?"}),
  ).toBeVisible();
  await expect(page.locator('.reference-home-main')).toHaveCSS('opacity', '1');
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBe(390);
  await page.screenshot({
    path: assetPath('faithful-home-mobile-2026-07-13.png'),
    fullPage: false,
  });
});

test('Goal Report renders at the required desktop viewport', async ({page, api}) => {
  const {id} = await api.createRun({
    research_goal: 'Visual acceptance goal report',
    tier: 'standard',
  });
  await api.startRun(id);
  await expect.poll(async () => (await api.getRun(id)).status).toBe('completed');
  await page.setViewportSize({width: 1440, height: 720});
  await page.goto(`/runs/${id}/ideas`);

  await expect(page.getByRole('button', {name: 'Share'})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Open Agent'})).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBe(1440);
  await page.screenshot({
    path: assetPath('faithful-goal-report-desktop-2026-07-13.png'),
    fullPage: false,
  });
});

test('Goal Report remains reachable at the required mobile viewport', async ({
  page,
  api,
}) => {
  const {id} = await api.createRun({
    research_goal: 'Mobile visual acceptance goal report',
    tier: 'standard',
  });
  await api.startRun(id);
  await expect.poll(async () => (await api.getRun(id)).status).toBe('completed');
  await page.setViewportSize({width: 390, height: 780});
  await page.goto(`/runs/${id}/ideas`);

  await expect(page.getByRole('button', {name: 'Open Agent'})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Share'})).toBeVisible();
  await expect(page.getByRole('link', {name: 'Download'})).toBeVisible();
  await page.getByRole('button', {name: 'Run Specifications'}).click();
  await expect(page.getByRole('heading', {name: 'Run Specifications'})).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBe(390);
  await page.screenshot({
    path: assetPath('faithful-goal-report-mobile-2026-07-13.png'),
    fullPage: false,
  });
});
