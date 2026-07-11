import {expect, test} from '../support/fixtures';

// Flow: the session-home page renders the three seeded demo runs. This also
// doubles as the plumbing smoke — it is the first thing that must work, since
// it proves both servers booted, the frontend reached the isolated backend
// cross-origin, and the seeded demo data rendered.
//
// Runs before the create/cancel flows (which add owned runs) so the home
// surface here shows only the demo runs. Presence, not counts, is asserted:
// each demo goal carries a stable, distinctive phrase.
const DEMO_GOAL_PHRASES = [
  /staphylococcus aureus/i,
  /synaptic pruning/i,
  /ferroptosis/i,
];

test('home page renders the seeded demo runs', async ({page}) => {
  await page.goto('/');

  // The desktop Recents panel is the app's own shell chrome.
  await expect(page.getByRole('heading', {name: /recents/i})).toBeVisible();

  // Scope to the recents panel: some home-stage suggestion prompts share
  // wording with the demo goals (e.g. "synaptic pruning"), so a page-wide
  // text match would resolve to a hidden suggestion-preview bubble.
  const recents = page.getByRole('complementary', {name: /recent runs/i});

  // Each seeded demo run's goal appears on its recents card.
  for (const phrase of DEMO_GOAL_PHRASES) {
    await expect(recents.getByText(phrase).first()).toBeVisible();
  }

  // The cards are links into each run's detail page.
  const demoCards = recents
    .getByRole('link')
    .filter({hasText: /staphylococcus aureus/i});
  await expect(demoCards.first()).toBeVisible();
});
