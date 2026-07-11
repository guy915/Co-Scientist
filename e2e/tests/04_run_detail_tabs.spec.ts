import {expect, test} from '../support/fixtures';

// Flow: the run-detail tabs (details / ideas / learning / overview) render a
// completed run's hypotheses (with Elo scores) and report content.
//
// A seeded demo run is used for stable, fully-synthesized content: the test
// opens it from the home recents list and walks every tab.
test('run detail tabs render hypotheses, Elo scores, and report content', async ({
  page,
}) => {
  await page.goto('/');

  // Open the Staphylococcus aureus demo run from its recents card.
  const demoCard = page
    .getByRole('complementary', {name: /recent runs/i})
    .getByRole('link')
    .filter({hasText: /staphylococcus aureus/i})
    .first();
  await demoCard.click();
  await expect(page).toHaveURL(/\/runs\/[^/]+\/details/);

  // Details tab (default): the research goal and its details document.
  await expect(
    page.getByRole('heading', {name: /research goal details/i}),
  ).toBeVisible();
  await expect(page.getByText(/staphylococcus aureus/i).first()).toBeVisible();

  // Ideas tab: the Elo-ranked hypothesis list.
  await page.getByRole('button', {name: 'All Ideas'}).click();
  await expect(
    page.getByRole('list', {name: /ranked hypothesis list/i}),
  ).toBeVisible();
  await expect(page.getByText(/elo rating:/i).first()).toBeVisible();

  // Learning tab: the synthesized learning sections and searchable references.
  await page.getByRole('button', {name: 'Learning'}).click();
  await expect(page.getByRole('heading', {name: /references/i})).toBeVisible();
  await expect(
    page.getByRole('textbox', {name: /search references/i}),
  ).toBeVisible();

  // Overview tab: the synthesized report (winning ideas + tournament summary).
  await page.getByRole('button', {name: 'Research Overview'}).click();
  await expect(
    page.getByRole('heading', {name: /research overview/i}),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', {name: /winning ideas/i}),
  ).toBeVisible();
  await expect(page.getByText(/tournament matches have been recorded/i)).toBeVisible();
});
