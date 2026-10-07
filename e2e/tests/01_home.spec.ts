import {MOBILE_VIEWPORT, expect, test} from '../support/fixtures';

test.describe('home', () => {
test('faithful home lists seeded demo runs in recents', async ({page}) => {
  await page.goto('/');

  await expect(page.getByRole('heading', {name: /recents/i})).toBeVisible();

  const recents = page.getByRole('complementary', {name: /recent runs/i});

  // Wait for seeded demos before checking an empty panel or the history fetch
  // can race it.
  await expect(recents.getByRole('link')).toHaveCount(3);
  await expect(
    recents.getByText(/you have not started any sessions yet/i),
  ).not.toBeVisible();
});

test('closed phone drawer keeps its chat links out of the tab order', async ({
  page,
}) => {
  await page.setViewportSize(MOBILE_VIEWPORT);
  await page.goto('/');
  const nav = page.getByRole('complementary', {name: 'Primary navigation'});
  const chatLinks = nav.locator('.ucs-chat-list a');
  await expect(chatLinks.first()).toBeHidden();

  await page.getByRole('button', {name: 'Open navigation'}).click();
  await expect(chatLinks.first()).toBeVisible();
});
});

test.describe('not found', () => {
test('unknown route shows the 404 page', async ({page}) => {
  await page.goto('/this/route/definitely/does/not/exist');

  await expect(
    page.getByRole('heading', {name: /page not found/i}),
  ).toBeVisible();
  await expect(page.getByText('404')).toBeVisible();
  await expect(page.getByRole('link', {name: /return home/i})).toBeVisible();
});
});
