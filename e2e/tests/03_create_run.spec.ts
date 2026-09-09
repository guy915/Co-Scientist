import {type Page} from '@playwright/test';
import {expect, test} from '../support/fixtures';

const GOAL =
  'What molecular checkpoints govern ferroptosis escape in ' +
  'glioblastoma stem cells?';

// Fill the composer with the research goal, attach a private pilot-result file,
// and submit to kick off the model-driven interview.
async function draftGoalInComposer(page: Page): Promise<void> {
  const composer = page.getByRole('textbox');
  await composer.click();
  await composer.fill(GOAL);
  await page.locator('input[type="file"]').setInputFiles({
    name: 'private-lactate-result.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from(
      'Private pilot result: MCT1 perturbation delayed synaptic ATP recovery.',
    ),
  });
  await expect(page.getByText('private-lactate-result.txt')).toBeVisible();
  await composer.press('Enter');
}

// The Agent runs a short, model-driven interview whose questions are generated
// from the goal (their exact wording is not fixed) and which completes into an
// editable research plan. Answer each question that appears until the plan's
// "Start research" action is offered, rather than asserting on specific
// question copy, then confirm the completed plan.
async function answerInterviewUntilPlan(page: Page): Promise<void> {
  const startButton = page.getByRole('button', {name: 'Start research'});
  const assistantTurns = page.getByRole('button', {name: 'Copy response'});
  await expect(assistantTurns.first()).toBeVisible({timeout: 30_000});
  const answers = [
    'Prioritize GPX4-independent lipid repair mechanisms.',
    'Use patient-derived organoids and isogenic controls.',
    'Optimize for translational relevance to recurrent glioblastoma.',
    'No further constraints; proceed with the strongest directions.',
  ];
  for (const answer of answers) {
    if (await startButton.isVisible().catch(() => false)) break;
    const priorTurns = await assistantTurns.count();
    await page.getByRole('textbox').last().fill(answer);
    await page.getByRole('button', {name: 'Send'}).click();
    // The answer is consumed once the plan is ready or the model posts its
    // next question (a new assistant response bubble appears).
    await expect(async () => {
      const ready = await startButton.isVisible().catch(() => false);
      const advanced = (await assistantTurns.count()) > priorTurns;
      expect(ready || advanced).toBeTruthy();
    }).toPass({timeout: 30_000});
  }

  // The completed interview produces the editable research plan.
  await expect(startButton).toBeVisible({timeout: 30_000});
  await expect(page.getByText(GOAL).first()).toBeVisible();
}

/**
 * The plan turn must open at its *own* top, not the conversation's.
 *
 * The auto-scroll used to set the timeline's scrollTop to 0 when the plan
 * card arrived, which is the top of the whole conversation -- past a couple
 * of turns the scientist was thrown back to their opening message the moment
 * the plan was produced. Only a real browser lays the timeline out, so this
 * is the one place the geometry can be observed.
 */
async function assertPlanOpensAtItsOwnTop(page: Page): Promise<void> {
  await expect(async () => {
    const metrics = await page.evaluate(() => {
      const scroller = document.querySelector('.reference-chat-timeline');
      const card = document.querySelector('[data-timeline-anchor="draft-spec"]');
      if (!scroller || !card) return null;
      return {
        scrollTop: scroller.scrollTop,
        overflows: scroller.scrollHeight > scroller.clientHeight,
        viewport: scroller.clientHeight,
        cardOffset:
          card.getBoundingClientRect().top -
          scroller.getBoundingClientRect().top,
      };
    });
    expect(metrics).not.toBeNull();
    // A conversation short enough to fit has no scroll position to get
    // wrong, so there is nothing here to observe.
    if (!metrics!.overflows) return;
    expect(metrics!.scrollTop).toBeGreaterThan(0);
    expect(metrics!.cardOffset).toBeGreaterThan(-8);
    expect(metrics!.cardOffset).toBeLessThan(metrics!.viewport);
  }).toPass({timeout: 10_000});
}

// Click "Start research" and capture both lifecycle mutations as direct
// evidence that the browser owns and starts the same draft through the
// cross-origin development topology. Returns the created run id.
async function startRunFromPlan(page: Page): Promise<string> {
  const createdPromise = page.waitForResponse(
    response =>
      new URL(response.url()).pathname === '/api/runs' &&
      response.request().method() === 'POST',
  );
  const startAttemptPromise = page.waitForResponse(
    response =>
      /\/api\/runs\/[^/]+\/start$/.test(new URL(response.url()).pathname) &&
      response.request().method() === 'POST',
  );
  // The Agent's reply to the start request, which the session card renders as
  // its lead-in. Captured here because a wrong route or frame vocabulary is
  // invisible to either side's unit tests -- the card would simply show its
  // standby copy, which is also what a correct offline run shows.
  const announcedPromise = page.waitForResponse(
    response =>
      /\/api\/runs\/[^/]+\/messages\/started$/.test(
        new URL(response.url()).pathname,
      ) && response.request().method() === 'POST',
  );
  await page.getByRole('button', {name: 'Start research'}).click();
  const created = await createdPromise;
  expect(created.status()).toBe(200);
  const {id} = (await created.json()) as {id: string};
  const startAttempt = await startAttemptPromise;
  expect(startAttempt.status()).toBe(200);
  const announced = await announcedPromise;
  expect(announced.status()).toBe(200);
  expect(await announced.text()).toContain('"type": "done"');
  await expect(
    page.getByRole('region', {name: 'Started research session'}),
  ).toBeVisible();
  return id;
}

// Open the run detail. Capture the SSE stream opening (browser -> backend) as
// direct evidence the live event channel was established.
async function openRunDetail(page: Page, id: string): Promise<void> {
  const ssePromise = page.waitForResponse(
    response => /\/api\/runs\/[^/]+\/events/.test(response.url()),
    {timeout: 30_000},
  );
  await page.goto(`/runs/${id}/specifications`);
  const sse = await ssePromise;
  expect(sse.status()).toBe(200);
  await expect(page).toHaveURL(/\/runs\/[^/]+\/specifications/);
}

// The top-ranked idea (auto-selected on desktop) shows the mature review
// cascade's structured findings -- proof that the offline backend's review
// scores clear the initial "viable" gate and comprehensive_reflection's
// full/simulation review batch actually ran for it, not just the quick
// initial screen. The simulation review's fields (failure_points,
// decisive_step) are unconditionally required in SIMULATION_REVIEW_SCHEMA;
// the full/recurrent review's go_no_go_recommendation/time_to_verdict are
// optional in FULL_REVIEW_SCHEMA but named in offline_llm's
// _OPTIONAL_FIELD_HINTS, so the offline backend fills them too -- see
// ideas_detail_review_findings.tsx's SimulationFindings/VerdictLines and
// drain_reviews.py's detail_json build.
async function assertIdeasTabShowsMatureReviews(page: Page): Promise<void> {
  const detail = page.getByRole('region', {name: 'Hypothesis detail'});
  const fullReviewHeading = detail.getByRole('heading', {
    name: 'Full review',
    exact: true,
  });
  await expect(fullReviewHeading).toBeVisible();
  await expect(
    detail.getByRole('heading', {name: 'Simulation review', exact: true}),
  ).toBeVisible();
  // Scoped to the Full review row's own container (its parent), not the
  // whole detail pane: a recurrent review row, if one also rendered, would
  // carry the same "Verdict:"/"Time to verdict:" lines and break
  // Playwright's strict single-match mode.
  const fullReviewSection = fullReviewHeading.locator('xpath=..');
  await expect(
    fullReviewSection.getByText('Verdict:', {exact: true}),
  ).toBeVisible();
  await expect(
    fullReviewSection.getByText('Time to verdict:', {exact: true}),
  ).toBeVisible();
  // exact: true, since the simulation critique paragraph also flattens
  // "Failure point: .../Decisive step: ..." into its own prose -- without
  // it this resolves two elements and Playwright's strict mode fails.
  await expect(
    detail.getByText('Failure point:', {exact: true}),
  ).toBeVisible();
  await expect(
    detail.getByText('Decisive step:', {exact: true}),
  ).toBeVisible();
}

// The overview report's research-directions preview list, gated on 2+ named
// directions (report_markdown_overview.py::_render_directions_preview,
// mirrored in the frontend's DirectionsPreview) -- proof the offline
// backend's research_overview call is sized past that gate rather than
// defaulting to the generic filler's one item per array.
async function assertOverviewTabShowsDirectionsPreview(
  page: Page,
): Promise<void> {
  await expect(
    page.getByRole('heading', {name: 'Research directions', level: 3}),
  ).toBeVisible();
  const preview = page
    .getByText('We will be focusing on these research directions:')
    .locator('xpath=following-sibling::ul[1]');
  await expect(preview.getByRole('listitem')).toHaveCount(3);
}

// The Goal Report tabs appear only after the run reaches publication. Walk the
// All Ideas, Research Overview, and Learning tabs to observe the streamed run
// reaching completion.
//
// The tab strip is a nav of real deep-linkable links (not buttons), so each
// tab is matched by its link role and its exact accessible name -- the labels
// ReportTabNav renders in run_detail_shell.tsx.
async function assertStreamedRunCompletes(page: Page): Promise<void> {
  const ideasTab = page.getByRole('link', {name: 'All Ideas', exact: true});
  await expect(ideasTab).toBeVisible({timeout: 30_000});
  await ideasTab.click();
  await expect(
    page.getByRole('list', {name: /ranked hypothesis list/i}),
  ).toBeVisible();
  await assertIdeasTabShowsMatureReviews(page);
  await page
    .getByRole('link', {name: 'Research Overview', exact: true})
    .click();
  // level: 3 picks the section heading, not a per-aim "Specific Aims N"
  // heading (h4) -- both answer to the same phrase since
  // OVERVIEW-AIMS-VOCABULARY-001 gave each aim a numbered heading of its
  // own, mirroring the "Research directions" heading check below.
  await expect(
    page.getByRole('heading', {name: /specific aims/i, level: 3}),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', {name: /agent insights/i}),
  ).toBeVisible();
  await assertOverviewTabShowsDirectionsPreview(page);
  await page.getByRole('link', {name: 'Learning', exact: true}).click();
  await expect(page.getByText('private-lactate-result.txt')).toBeVisible();
}

// Flow: create a run from the chat workspace, start it, watch the live
// pipeline drive the run-detail surface over SSE, and see it complete.
//
// The run is created and started entirely through the UI (composer -> draft
// spec card -> Start research -> started card). Opening the run detail mounts
// the SSE subscription; the Ideas and Overview tabs then populate only because
// streamed pipeline events (generate/ranking/report) drove the refetches, so
// asserting on the Elo-ranked hypotheses and the synthesized report is a
// genuine observation of the streamed run reaching completion.
test('creates a run from chat, starts it, and watches it complete', async ({
  page,
}) => {
  await page.goto('/');
  await draftGoalInComposer(page);
  await answerInterviewUntilPlan(page);
  await assertPlanOpensAtItsOwnTop(page);
  const id = await startRunFromPlan(page);
  await openRunDetail(page, id);
  await assertStreamedRunCompletes(page);
});
