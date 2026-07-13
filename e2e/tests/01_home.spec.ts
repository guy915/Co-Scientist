import {expect, test} from '../support/fixtures';

// Flow: the faithful session-home page quarantines seeded demo runs. This also
// doubles as the plumbing smoke — it is the first thing that must work, since
// it proves both servers booted, the frontend reached the isolated backend
// cross-origin, and the seeded demo data rendered.
//
test('faithful home quarantines seeded demo runs', async ({page}) => {
  await page.goto('/');

  // The desktop Recents panel is the app's own shell chrome.
  await expect(page.getByRole('heading', {name: /recents/i})).toBeVisible();

  const recents = page.getByRole('complementary', {name: /recent runs/i});
  await expect(
    recents.getByText(/you have not started any sessions yet/i),
  ).toBeVisible();
  await expect(recents.getByRole('link')).toHaveCount(0);
});
