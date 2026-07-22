import {fileURLToPath} from 'node:url';

import {expect, test} from '../support/fixtures';

// Screenshots are build artifacts, not tracked docs assets: write them under
// e2e/test-results/, which e2e/.gitignore already covers, so a local run never
// leaves untracked PNGs in docs/assets/ for a later `git add -A` to pick up.
function assetPath(name: string): string {
  return fileURLToPath(new URL(`../test-results/${name}`, import.meta.url));
}

test('faithful home renders at the required desktop viewport', async ({page}) => {
  await page.setViewportSize({width: 1440, height: 720});
  await page.goto('/');

  await expect(
    page.getByRole('heading', {
      name: 'What breakthrough should we make today?',
    }),
  ).toBeVisible();
  await expect(page.locator('.reference-home-main')).toHaveCSS('opacity', '1');
  // The general-audience workbench surfaces the Logs popover in the header
  // (audience-gated in layout_header.tsx); it is part of the faithful render.
  await expect(page.getByRole('button', {name: /Logs/i})).toBeVisible();
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
    page.getByRole('heading', {
      name: 'What breakthrough should we make today?',
    }),
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

  // The completed Goal Report's Ideas surface renders the Elo-ranked list.
  await expect(
    page.getByRole('list', {name: /ranked hypothesis list/i}),
  ).toBeVisible();
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

  // The completed Goal Report's Ideas surface renders the Elo-ranked list.
  await expect(
    page.getByRole('list', {name: /ranked hypothesis list/i}),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBe(390);
  await page.screenshot({
    path: assetPath('faithful-goal-report-mobile-2026-07-13.png'),
    fullPage: false,
  });
});
