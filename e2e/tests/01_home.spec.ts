import {expect, test} from '../support/fixtures';

// Flow: the faithful session-home page lists the seeded demo runs in Recents.
// This also doubles as the plumbing smoke -- it is the first thing that must
// work, since it proves both servers booted, the frontend reached the
// isolated backend cross-origin, and the seeded demo data rendered.
//
test('faithful home lists seeded demo runs in recents', async ({page}) => {
  await page.goto('/');

  // The desktop Recents panel is the app's own shell chrome.
  await expect(page.getByRole('heading', {name: /recents/i})).toBeVisible();

  const recents = page.getByRole('complementary', {name: /recent runs/i});

  // Wait for the 3 seeded demo runs to land first: the panel mounts empty and
  // swaps them in once loadRunHistory() resolves, so asserting the empty
  // state before this settles races that fetch.
  await expect(recents.getByRole('link')).toHaveCount(3);
  await expect(
    recents.getByText(/you have not started any sessions yet/i),
  ).not.toBeVisible();
});
