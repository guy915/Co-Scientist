import {expect, test} from '../support/fixtures';

// Flow: an unknown route renders the 404 page (the catch-all `*` route in
// workbench_app.tsx).
test('unknown route shows the 404 page', async ({page}) => {
  await page.goto('/this/route/definitely/does/not/exist');

  await expect(page.getByRole('heading', {name: /page not found/i})).toBeVisible();
  await expect(page.getByText('404')).toBeVisible();
  await expect(page.getByRole('link', {name: /return home/i})).toBeVisible();
});
