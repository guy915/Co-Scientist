import {type Page} from '@playwright/test';
import {CLIENT_ID, expect, test} from '../support/fixtures';

test.describe('create run', () => {
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
// optional in FULL_REVIEW_SCHEMA but named in offline.llm's
// _OPTIONAL_FIELD_HINTS, so the offline backend fills them too -- see
// ideas_detail_review_findings.tsx's SimulationFindings/VerdictLines and
// drain/reviews.py's detail_json build.
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
// directions (report/markdown/overview.py::_render_directions_preview,
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

test('manually continues a linked draft after a lost create response', async ({
  browser,
  page,
  api,
}) => {
  const createBodies: Record<string, unknown>[] = [];
  const createKeys: string[] = [];
  const startRequests: string[] = [];
  let resolveCreated!: (id: string) => void;
  const createdPromise = new Promise<string>(resolve => {
    resolveCreated = resolve;
  });
  let releaseCreateResponse!: () => void;
  const createResponseGate = new Promise<void>(resolve => {
    releaseCreateResponse = resolve;
  });
  let resolveStartForwarded!: () => void;
  const startForwarded = new Promise<void>(resolve => {
    resolveStartForwarded = resolve;
  });
  let releaseStartResponse!: () => void;
  const startResponseGate = new Promise<void>(resolve => {
    releaseStartResponse = resolve;
  });

  await page.context().route('**/api/runs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    createBodies.push(
      route.request().postDataJSON() as Record<string, unknown>,
    );
    createKeys.push(route.request().headers()['idempotency-key'] ?? '');
    if (createBodies.length > 1) return route.continue();

    // The API commits the run and interview link, but the browser loses the
    // response before it can save the returned run id.
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    const {id} = (await response.json()) as {id: string};
    resolveCreated(id);
    await createResponseGate;
    await route.abort('failed');
  });
  await page.context().route('**/api/runs/*/start', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    startRequests.push(route.request().url());
    if (startRequests.length > 1) return route.continue();
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    const body = await response.text();
    const upstreamHeaders = response.headers();
    const headers = Object.fromEntries(
      Object.entries(upstreamHeaders).filter(([name]) =>
        [
          'access-control-allow-origin',
          'access-control-allow-credentials',
          'access-control-expose-headers',
          'content-type',
          'vary',
        ].includes(name),
      ),
    );
    resolveStartForwarded();
    await startResponseGate;
    await route.fulfill({
      status: response.status(),
      headers,
      body,
    });
  });

  await page.goto('/');
  await draftGoalInComposer(page);
  await answerInterviewUntilPlan(page);
  const chatUrl = page.url();
  const firstStartClick = page
    .getByRole('button', {name: 'Start research'})
    .click();
  const runId = await createdPromise;
  await expect(page.getByRole('button', {name: 'Starting...'})).toBeDisabled();
  releaseCreateResponse();
  await firstStartClick;
  await expect(page.getByRole('alert')).toBeVisible();
  expect(await api.getRun(runId)).toMatchObject({status: 'draft'});

  await page.reload();
  const continueButton = page.getByRole('button', {
    name: 'Continue research',
  });
  await expect(continueButton).toBeEnabled();
  expect(startRequests).toHaveLength(0);
  expect(createBodies).toHaveLength(1);
  const chatId = new URL(chatUrl).pathname.split('/').at(-1) ?? '';
  const storedRequestMatches = await page.evaluate(
    ({id, key, payload}) => {
      const saved = JSON.parse(
        sessionStorage.getItem(
          `co_scientist_pending_run_create:${encodeURIComponent(id)}`,
        ) ?? 'null',
      ) as {key?: string; payloadJson?: string} | null;
      if (!saved?.payloadJson) return false;
      return (
        saved.key === key &&
        JSON.stringify(JSON.parse(saved.payloadJson)) ===
          JSON.stringify(payload)
      );
    },
    {id: chatId, key: createKeys[0], payload: createBodies[0]},
  );
  expect(storedRequestMatches).toBe(true);

  // A different owner cannot reopen the interview or see its recovery action.
  const otherContext = await browser.newContext();
  await otherContext.addInitScript(clientId => {
    window.localStorage.setItem('co_scientist_client_id', clientId);
  }, `${CLIENT_ID}-other`);
  const otherPage = await otherContext.newPage();
  await otherPage.goto(chatUrl);
  await expect(
    otherPage.getByRole('button', {name: 'Continue research'}),
  ).toHaveCount(0);
  expect(startRequests).toHaveLength(0);
  expect(await api.getRun(runId)).toMatchObject({status: 'draft'});
  await otherContext.close();

  // Native button semantics make the recovery action available by keyboard.
  await continueButton.focus();
  const continueByKeyboard = continueButton.press('Enter');
  await startForwarded;
  await expect(
    page.getByRole('button', {name: 'Continuing...'}),
  ).toBeDisabled();
  await expect(
    page.getByText('Continuing research', {exact: true}),
  ).toBeVisible();
  releaseStartResponse();
  await continueByKeyboard;

  await expect(
    page.getByRole('region', {name: 'Started research session'}),
  ).toBeVisible();
  expect(startRequests).toHaveLength(1);
  expect(createBodies).toHaveLength(1);
  expect(await api.getRun(runId)).not.toMatchObject({status: 'draft'});

  // Reopening a queued/running run shows it as the existing session and
  // never creates or starts another one.
  await page.reload();
  await expect(
    page.getByRole('region', {name: 'Started research session'}),
  ).toBeVisible();
  expect(startRequests).toHaveLength(1);
  expect(createBodies).toHaveLength(1);
});
});

test.describe('run detail tabs', () => {
// Flow: the run-detail tabs (details / ideas / learning / overview) render a
// completed run's hypotheses (with Elo scores) and report content.
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
});
});

test.describe('cancel', () => {
// Flow: cancel a running run and observe its terminal state in the UI.
//
// There is deliberately no in-product affordance to cancel a run (adding one
// would be a forbidden behavior change), so the run is created, started, and
// cancelled over the backend API — every call tagged with the same
// X-Client-ID the browser uses, so the run is owned by this browser session
// and surfaces on its home recents list. The observable under test is the
// terminal state rendered in the UI: the recents card's "Status: Cancelled"
// chip.
//
// Determinism: the run is sized large (extra iterations and hypotheses) so it
// stays active long enough to catch running and to land a cooperative cancel
// at an iteration checkpoint well before it could finish. What the card renders
// depends only on the terminal status polled below, not on how far the run
// progressed — so the assertion holds whether the cancel lands early or late.
test('cancels a running run and shows the cancelled state on home', async ({
  page,
  api,
}) => {
  const goal = 'Long-running cancellation probe for the browser e2e harness';

  const {id} = await api.createRun({
    research_goal: goal,
    tier: 'extended',
    max_iterations: 8,
    initial_hypotheses_count: 30,
  });
  await api.startRun(id);

  // Wait until the workflow is actually running before cancelling.
  await expect
    .poll(async () => (await api.getRun(id)).status, {
      timeout: 20_000,
      intervals: [200],
    })
    .toMatch(/running|synthesizing/);

  await api.cancelRun(id);

  // Cancellation is cooperative; the workflow lands in CANCELLED at its next
  // checkpoint.
  await expect
    .poll(async () => (await api.getRun(id)).status, {
      timeout: 20_000,
      intervals: [200],
    })
    .toBe('cancelled');

  // The owned run surfaces on the session-home Recents, and its card reports
  // the terminal state. Scoped to the Recents aside (rather than any link on
  // the page) so a same-goal link elsewhere cannot stand in for it, and the
  // assertions wait for the async history render rather than racing it.
  await page.goto('/');
  const recents = page.getByRole('complementary', {name: 'Recent runs'});
  const card = recents.getByRole('link').filter({hasText: goal});
  await expect(card).toBeVisible();
  await expect(card.getByText(/status:\s*cancelled/i)).toBeVisible();
});
});
