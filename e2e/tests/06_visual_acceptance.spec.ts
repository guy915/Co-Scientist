import {
  DESKTOP_VIEWPORT,
  MOBILE_VIEWPORT,
  captureViewport,
  createCompletedRun,
  expect,
  test,
} from '../support/fixtures';

// Each test sizes the page from one shared Viewport and hands that same
// object to captureViewport, which asserts no horizontal overflow at its
// width before taking the shot — so the sized width and the asserted width
// are one value, not two that can drift.

test('home renders at the required desktop viewport', async ({page}) => {
  await page.setViewportSize(DESKTOP_VIEWPORT);
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
  await captureViewport(page, {
    ...DESKTOP_VIEWPORT,
    name: 'faithful-home-desktop-2026-07-13.png',
  });
});

test('home renders at the required mobile viewport', async ({page}) => {
  await page.setViewportSize(MOBILE_VIEWPORT);
  await page.goto('/');

  await expect(
    page.getByRole('heading', {
      name: 'What breakthrough should we make today?',
    }),
  ).toBeVisible();
  await expect(page.locator('.reference-home-main')).toHaveCSS('opacity', '1');
  await captureViewport(page, {
    ...MOBILE_VIEWPORT,
    name: 'faithful-home-mobile-2026-07-13.png',
  });
});

test('Goal Report renders at the desktop viewport', async ({page, api}) => {
  const id = await createCompletedRun(api, {
    research_goal: 'Visual acceptance goal report',
    tier: 'standard',
  });
  await page.setViewportSize(DESKTOP_VIEWPORT);
  await page.goto(`/runs/${id}/ideas`);

  // The completed Goal Report's Ideas surface renders the Elo-ranked list.
  await expect(
    page.getByRole('list', {name: /ranked hypothesis list/i}),
  ).toBeVisible();
  await captureViewport(page, {
    ...DESKTOP_VIEWPORT,
    name: 'faithful-goal-report-desktop-2026-07-13.png',
  });
});

test('Goal Report remains reachable at the required mobile viewport', async ({
  page,
  api,
}) => {
  const id = await createCompletedRun(api, {
    research_goal: 'Mobile visual acceptance goal report',
    tier: 'standard',
  });
  await page.setViewportSize(MOBILE_VIEWPORT);
  await page.goto(`/runs/${id}/ideas`);

  // The completed Goal Report's Ideas surface renders the Elo-ranked list.
  await expect(
    page.getByRole('list', {name: /ranked hypothesis list/i}),
  ).toBeVisible();
  await captureViewport(page, {
    ...MOBILE_VIEWPORT,
    name: 'faithful-goal-report-mobile-2026-07-13.png',
  });
});
