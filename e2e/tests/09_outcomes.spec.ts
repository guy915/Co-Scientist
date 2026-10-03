import {createCompletedRun, expect, test} from '../support/fixtures';
import {E2E_RESEARCHER_ACCESS_CODE, API_URL} from '../support/paths';

test.describe('empirical outcomes', () => {
test("records an outcome on an owned run and keeps it beside the report", async ({
  page,
  api,
}) => {
  const accessToken = await api.exchangeAccessCode(E2E_RESEARCHER_ACCESS_CODE);
  const researcherApi = api.asResearcher(accessToken);
  const runId = await createCompletedRun(researcherApi, {
    research_goal: "Owned empirical outcome submission test",
    tier: "standard",
  });
  const requests: {
    method: string;
    clientId?: string;
    authorization?: string;
  }[] = [];
  await page.route(`**/api/runs/${runId}/outcomes`, async (route) => {
    requests.push({
      method: route.request().method(),
      clientId: route.request().headers()["x-client-id"],
      authorization: route.request().headers().authorization,
    });
    await route.continue();
  });
  await page.route(
    `**/api/runs/${runId}/hypotheses/*/outcomes`,
    async (route) => {
      const request = route.request();
      requests.push({
        method: request.method(),
        clientId: request.headers()["x-client-id"],
        authorization: request.headers().authorization,
      });
      await route.continue();
    },
  );

  const unsignedGet = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      response.url().endsWith(`/api/runs/${runId}/outcomes`),
  );
  await page.goto(`/runs/${runId}/ideas`);
  await expect(
    page.getByRole("heading", { name: "Scientist-recorded observations" }),
  ).toBeVisible();
  const denied = await unsignedGet;
  expect(denied.status()).toBe(401);
  await expect(
    page.getByText("Sign in with researcher access to view or record observations."),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Researcher access" })).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Record an observation" }),
  ).toHaveCount(0);
  expect(requests[0]).toMatchObject({
    method: "GET",
    clientId: "e2e-client",
  });
  expect(requests[0].authorization).toBeUndefined();

  await page.getByRole("link", { name: "Researcher access" }).click();
  await expect(page.getByRole("heading", { name: "Researcher access" })).toBeVisible();
  await page.getByLabel("Access code").fill(E2E_RESEARCHER_ACCESS_CODE);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(await page.evaluate(() => sessionStorage.getItem("co_scientist_access_token"))).toBeTruthy();

  const signedGet = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      response.url().endsWith(`/api/runs/${runId}/outcomes`),
  );
  await page.goto(`/runs/${runId}/ideas`);
  expect((await signedGet).status()).toBe(200);
  await expect(
    page.getByRole("group", { name: "Record an observation" }),
  ).toBeVisible();

  const method = page.getByRole("textbox", { name: "Method or protocol" });
  await method.focus();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("textbox", { name: "Conditions" })).toBeFocused();

  await method.fill("Western blot");
  await page
    .getByRole("textbox", { name: "Conditions" })
    .fill("24 hour treatment");
  await page
    .getByRole("textbox", { name: "Measured observation" })
    .fill("Signal rose by two fold");
  await page
    .getByRole("textbox", { name: "Units (optional)" })
    .fill("fold change");
  await page.getByRole("textbox", { name: "Controls" }).fill("Vehicle control");
  await page
    .getByRole("textbox", { name: "Interpretation" })
    .fill("Consistent with the prediction");
  await page
    .getByRole("textbox", { name: /Referenced evidence IDs/ })
    .fill("ev-e2e-1, ev-e2e-2");

  const rejectedResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes(`/api/runs/${runId}/hypotheses/`),
  );
  await page.getByRole("button", { name: "Record observation" }).click();
  const rejected = await rejectedResponse;
  expect(rejected.status()).toBe(404);
  expect(await rejected.json()).toMatchObject({
    detail: "hypothesis or evidence not found in this run",
  });
  await expect(page.getByRole("alert")).toContainText(
    "hypothesis or evidence not found in this run",
  );
  await expect(
    page.getByRole("textbox", { name: "Measured observation" }),
  ).toHaveValue("Signal rose by two fold");
  await page.getByRole("textbox", { name: /Referenced evidence IDs/ }).fill("");

  const savedResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes(`/api/runs/${runId}/hypotheses/`),
  );
  await page.getByRole("button", { name: "Record observation" }).click();
  const response = await savedResponse;
  expect(response.status(), await response.text()).toBe(201);
  await expect(page.getByText("Signal rose by two fold")).toBeVisible();
  await page.getByRole("button", { name: "Refresh observations" }).click();

  await page
    .getByRole("link", { name: "Research Overview", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Scientist-recorded empirical outcomes",
    }),
  ).toBeVisible();
  await expect(page.getByText("Signal rose by two fold")).toBeVisible();

  await page.reload();
  await expect(
    page.getByRole("heading", {
      name: "Scientist-recorded empirical outcomes",
    }),
  ).toBeVisible();
  await expect(page.getByText("Signal rose by two fold")).toBeVisible();
  const signedRequests = requests.filter((request) => request.authorization);
  expect(signedRequests.length).toBeGreaterThanOrEqual(4);
  expect(
    signedRequests.every(
      (request) =>
        request.authorization?.startsWith("Bearer ") &&
        request.clientId === undefined,
    ),
  ).toBe(true);
});

test("public demo observations stay visible without a submission form", async ({
  page,
  api,
}) => {
  const demo = (await api.listDemoRuns()).find((run) =>
    /staphylococcus aureus/i.test(run.research_goal),
  );
  expect(demo).toBeTruthy();

  const demoOutcomes = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      response.url().endsWith(`/api/runs/${demo!.id}/outcomes`),
  );
  await page.goto(`/runs/${demo!.id}/ideas`);
  expect((await demoOutcomes).status()).toBe(200);
  await expect(
    page.getByRole("heading", { name: "Scientist-recorded observations" }),
  ).toBeVisible();
  await expect(
    page.getByText("Public demo observations are read-only."),
  ).toBeVisible();
  expect(
    page.getByRole("group", { name: "Record an observation" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Researcher access" }),
  ).toHaveCount(0);
  await page
    .getByRole("link", { name: "Research Overview", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Scientist-recorded empirical outcomes",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Researcher access" }),
  ).toHaveCount(0);
});
});

test.describe('outcome refinement status', () => {
test('requires an explicit owner click after refinement status can be refreshed', async ({
  page,
  api,
}) => {
  const token = await api.exchangeAccessCode(E2E_RESEARCHER_ACCESS_CODE);
  const researcherApi = api.asResearcher(token);
  const runId = await createCompletedRun(researcherApi, {
    research_goal:
      'Explain the Meselson–Stahl two-generation density-band result for DNA replication.',
    tier: 'standard',
  });
  const headers = {Authorization: `Bearer ${token}`};
  const hypothesesResponse = await page.request.get(
    `${API_URL}/api/runs/${runId}/hypotheses`,
    {headers},
  );
  expect(hypothesesResponse.status()).toBe(200);
  const hypotheses = (await hypothesesResponse.json()) as {
    hypotheses: {id: string}[];
  };
  const hypothesisId = hypotheses.hypotheses[0]?.id;
  expect(hypothesisId).toBeTruthy();
  // API and worker tests verify frozen source metadata. This case focuses on the
  // browser action.
  const outcomeFields = {
    method_protocol:
      'Grow E. coli for many generations with 15NH4Cl, shift to medium with a ten-fold excess of 14NH4Cl, and separate DNA by equilibrium sedimentation in a CsCl density gradient.',
    conditions:
      'Exponential growth after the isotope shift; observe DNA after one and two generation cycles.',
    measured_observation:
      'After one generation, only the intermediate-density hybrid band is present. After the second, equal amounts of intermediate-density hybrid and light DNA are present.',
    units:
      'Density-band class and relative amount; second-cycle amounts are 1:1.',
    controls:
      'Keep the published heavy-15N starting position and light-14N density position as band references. Add no unreported replicate count or separate control cohort.',
    interpretation:
      'The band pattern is consistent with semiconservative replication; this interpretation remains distinct from the measured bands.',
    referenced_evidence_ids: [],
  };
  const outcomeResponse = await page.request.post(
    `${API_URL}/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes`,
    {headers, data: outcomeFields},
  );
  expect(outcomeResponse.status(), await outcomeResponse.text()).toBe(201);
  const outcomeId = ((await outcomeResponse.json()) as {id: string}).id;

  await page.addInitScript(
    accessToken =>
      sessionStorage.setItem('co_scientist_access_token', accessToken),
    token,
  );
  const actionUrl =
    `**/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes/` +
    `${outcomeId}/refine`;
  let statusGets = 0;
  let actionPosts = 0;
  let refreshAllowed = false;
  let releaseInitialStatus!: () => void;
  const initialStatusBlocked = new Promise<void>(resolve => {
    releaseInitialStatus = resolve;
  });
  await page.route(actionUrl, async route => {
    if (route.request().method() === 'GET') {
      statusGets++;
      if (!refreshAllowed) {
        await initialStatusBlocked;
        await route.fulfill({
          status: 503,
          contentType: 'text/plain',
          body: 'API unavailable',
        });
        return;
      }
    }
    if (route.request().method() === 'POST') {
      actionPosts++;
      expect(route.request().headers()['idempotency-key']).toBe(
        `outcome-refinement:${runId}:${hypothesisId}:${outcomeId}`,
      );
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          action_id: 'offline-browser-action',
          run_id: runId,
          outcome_id: outcomeId,
          hypothesis_id: hypothesisId,
          task_idempotency_key: 'outcome-refinement:offline-browser-action',
          checkpoint_seq: 1,
          context_codepoints: 2_000,
          status: 'queued',
          child_hypothesis_id: null,
          created_at: 1_800_000_000,
          replayed: false,
        }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto(`/runs/${runId}/ideas`);
  await expect(
    page.getByText(outcomeFields.measured_observation),
  ).toBeVisible();
  await expect.poll(() => statusGets).toBeGreaterThan(0);
  await expect(
    page.getByText('Checking saved refinement status…'),
  ).toBeVisible();
  releaseInitialStatus();
  await expect(
    page.getByText('Could not load refinement status: 503 API unavailable'),
  ).toBeVisible();
  await expect(
    page.getByText(
      'This sends the linked hypothesis and this recorded outcome, with up to three source metadata links, to the run’s configured AI model to draft one follow-up hypothesis. AI output may be wrong. This action does not verify the observation or change existing claims, reviews, safety decisions, or ranking.',
    ),
  ).toBeVisible();
  await expect(
    page.getByRole('button', {
      name: 'Use outcome to refine this hypothesis',
    }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('button', {name: 'Refresh refinement status'}),
  ).toBeEnabled();
  expect(actionPosts).toBe(0);

  const getsBeforeRefresh = statusGets;
  refreshAllowed = true;
  await page.getByRole('button', {name: 'Refresh refinement status'}).click();
  await expect(
    page.getByRole('button', {
      name: 'Use outcome to refine this hypothesis',
    }),
  ).toBeEnabled();
  expect(statusGets).toBe(getsBeforeRefresh + 1);
  expect(actionPosts).toBe(0);

  const requestedAction = page.waitForResponse(
    response =>
      response
        .url()
        .includes(`/api/runs/${runId}/hypotheses/${hypothesisId}/`) &&
      response.url().endsWith(`/outcomes/${outcomeId}/refine`) &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', {name: 'Use outcome to refine this hypothesis'})
    .click();
  const response = await requestedAction;
  expect(response.status(), await response.text()).toBe(202);
  const action = (await response.json()) as {
    outcome_id: string;
    hypothesis_id: string;
    status: string;
  };
  expect(action.outcome_id).toBe(outcomeId);
  expect(action.hypothesis_id).toBe(hypothesisId);
  expect(action.status).toBe('queued');
  expect(actionPosts).toBe(1);
  await expect(page.getByText('Refinement request is queued.')).toBeVisible();
});

test('saved refinement stays visible in active and failed runs', async ({
  page,
  api,
}) => {
  const token = await api.exchangeAccessCode(E2E_RESEARCHER_ACCESS_CODE);
  const researcherApi = api.asResearcher(token);
  const runId = await createCompletedRun(researcherApi, {
    research_goal: 'Offline outcome-refinement status test',
    tier: 'standard',
  });
  const headers = {Authorization: `Bearer ${token}`};
  const hypothesesResponse = await page.request.get(
    `${API_URL}/api/runs/${runId}/hypotheses`,
    {headers},
  );
  expect(hypothesesResponse.status()).toBe(200);
  const hypotheses = (await hypothesesResponse.json()) as {
    hypotheses: {id: string}[];
  };
  const hypothesisId = hypotheses.hypotheses[0]?.id;
  expect(hypothesisId).toBeTruthy();
  const outcomeResponse = await page.request.post(
    `${API_URL}/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes`,
    {
      headers,
      data: {
        method_protocol: 'Density-gradient centrifugation',
        conditions: 'One generation in light nitrogen',
        measured_observation: 'One intermediate-density band',
        units: 'band density',
        controls: 'Heavy and light references',
        interpretation: 'Consistent with semiconservative replication',
        referenced_evidence_ids: [],
      },
    },
  );
  expect(outcomeResponse.status(), await outcomeResponse.text()).toBe(201);
  const outcomeId = ((await outcomeResponse.json()) as {id: string}).id;
  const completedRun = await researcherApi.getRun(runId);

  await page.addInitScript(
    accessToken =>
      sessionStorage.setItem('co_scientist_access_token', accessToken),
    token,
  );
  let visibleRunStatus = 'running';
  await page.route(`**/api/runs/${runId}`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({...completedRun, status: visibleRunStatus}),
    });
  });
  await page.route(
    `**/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes/${outcomeId}/refine`,
    route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          action_id: 'saved-refinement',
          run_id: runId,
          hypothesis_id: hypothesisId,
          outcome_id: outcomeId,
          task_idempotency_key: 'outcome-refinement:saved-refinement',
          checkpoint_seq: 1,
          context_codepoints: 100,
          status: visibleRunStatus === 'failed' ? 'failed' : 'running',
          child_hypothesis_id: null,
          created_at: 1_700_000_000,
          replayed: true,
        }),
      }),
  );

  await page.goto(`/runs/${runId}/ideas`);
  await expect(page.getByText('Refinement is running.')).toBeVisible();
  visibleRunStatus = 'failed';
  await page.reload();
  await expect(
    page.getByText('Refinement failed and remains available for owner retry.'),
  ).toBeVisible();
  await expect(
    page.getByRole('button', {name: /retry refinement/i}),
  ).toBeVisible();
});
});
