import {expect, test} from '../support/fixtures';

// Flow: the run-detail tabs (details / ideas / learning / overview /
// ranking) render a completed run's hypotheses (with Elo scores) and
// report content.
//
// A seeded demo run is used for stable, fully-synthesized content: the test
// opens it from the home recents list and walks every tab.
test('run detail tabs render hypotheses, Elo, and report content', async ({
  page,
  api,
}) => {
  const demos = await api.listDemoRuns();
  const demo = demos.find(run =>
    /staphylococcus aureus/i.test(run.research_goal),
  );
  expect(demo).toBeTruthy();
  await page.goto(`/runs/${demo!.id}/specifications`);

  // Details tab (default): the research goal and its details document.
  await expect(
    page.getByRole('heading', {name: /run specifications/i}),
  ).toBeVisible();
  await expect(page.getByText(/staphylococcus aureus/i).first()).toBeVisible();

  // All Ideas tab: the Elo-ranked hypothesis list. The tab strip is a nav of
  // real deep-linkable links (not buttons), so each tab is matched by its link
  // role and its exact accessible name -- the labels ReportTabNav renders in
  // run_detail_shell.tsx.
  await page.getByRole('link', {name: 'All Ideas', exact: true}).click();
  await expect(
    page.getByRole('list', {name: /ranked hypothesis list/i}),
  ).toBeVisible();
  await expect(page.getByText(/elo rating:/i).first()).toBeVisible();

  // Learning tab: the synthesized learning sections and searchable references.
  await page.getByRole('link', {name: 'Learning', exact: true}).click();
  await expect(page.getByRole('heading', {name: /references/i})).toBeVisible();
  await expect(
    page.getByRole('textbox', {name: /search references/i}),
  ).toBeVisible();

  // Overview tab: the synthesized report (winning ideas + tournament summary).
  await page
    .getByRole('link', {name: 'Research Overview', exact: true})
    .click();
  await expect(
    page.getByRole('heading', {name: /agent insights/i}),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', {name: /winning ideas/i}),
  ).toBeVisible();
  await expect(
    page.getByText(/tournament matches have been recorded/i),
  ).toBeVisible();

  // Top Ranking Hypotheses tab (R14-11): the second report document, a
  // seeded demo carries since it runs through the same finalize path.
  await page
    .getByRole('link', {name: 'Top Ranking Hypotheses', exact: true})
    .click();
  await expect(
    page.getByRole('heading', {name: 'Top hypotheses'}),
  ).toBeVisible();
  // The curated demo's top idea carries a full-review Go/No-Go verdict and
  // a simulation review, so this document is more than a bare heading.
  await expect(page.getByText(/verdict:/i).first()).toBeVisible();
  await expect(
    page.getByRole('heading', {name: /simulation review/i}).first(),
  ).toBeVisible();
});
