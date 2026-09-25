import { createCompletedRun, expect, test } from "../support/fixtures";
import { API_URL, E2E_RESEARCHER_ACCESS_CODE } from "../support/paths";

test("requires an explicit owner click after refinement status can be refreshed", async ({
  page,
  api,
}) => {
  const token = await api.exchangeAccessCode(E2E_RESEARCHER_ACCESS_CODE);
  const researcherApi = api.asResearcher(token);
  const runId = await createCompletedRun(researcherApi, {
    research_goal:
      "Explain the Meselson–Stahl two-generation density-band result for DNA replication.",
    tier: "standard",
  });
  const headers = { Authorization: `Bearer ${token}` };
  const hypothesesResponse = await page.request.get(
    `${API_URL}/api/runs/${runId}/hypotheses`,
    { headers },
  );
  expect(hypothesesResponse.status()).toBe(200);
  const hypotheses = (await hypothesesResponse.json()) as {
    hypotheses: { id: string }[];
  };
  const hypothesisId = hypotheses.hypotheses[0]?.id;
  expect(hypothesisId).toBeTruthy();
  const outcomeFields = {
    method_protocol:
      "Grow E. coli for many generations with 15NH4Cl, shift to medium with a ten-fold excess of 14NH4Cl, and separate DNA by equilibrium sedimentation in a CsCl density gradient.",
    conditions:
      "Exponential growth after the isotope shift; observe DNA after one and two generation cycles.",
    measured_observation:
      "After one generation, only the intermediate-density hybrid band is present. After the second, equal amounts of intermediate-density hybrid and light DNA are present.",
    units:
      "Density-band class and relative amount; second-cycle amounts are 1:1.",
    controls:
      "Keep the published heavy-15N starting position and light-14N density position as band references. Add no unreported replicate count or separate control cohort.",
    interpretation:
      "The band pattern is consistent with semiconservative replication; this interpretation remains distinct from the measured bands.",
    referenced_evidence_ids: [],
  };
  const outcomeResponse = await page.request.post(
    `${API_URL}/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes`,
    { headers, data: outcomeFields },
  );
  expect(outcomeResponse.status(), await outcomeResponse.text()).toBe(201);
  const outcomeId = ((await outcomeResponse.json()) as { id: string }).id;

  await page.addInitScript(
    (accessToken) =>
      sessionStorage.setItem("co_scientist_access_token", accessToken),
    token,
  );
  const actionUrl =
    `**/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes/` +
    `${outcomeId}/refine`;
  let statusGets = 0;
  let actionPosts = 0;
  let refreshAllowed = false;
  await page.route(actionUrl, async (route) => {
    if (route.request().method() === "GET") {
      statusGets++;
      if (!refreshAllowed) {
        await new Promise((resolve) => setTimeout(resolve, 300));
        await route.fulfill({
          status: 503,
          contentType: "text/plain",
          body: "API unavailable",
        });
        return;
      }
    }
    if (route.request().method() === "POST") {
      actionPosts++;
      expect(route.request().headers()["idempotency-key"]).toBe(
        `outcome-refinement:${runId}:${hypothesisId}:${outcomeId}`,
      );
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          action_id: "offline-browser-action",
          run_id: runId,
          outcome_id: outcomeId,
          hypothesis_id: hypothesisId,
          task_idempotency_key: "outcome-refinement:offline-browser-action",
          checkpoint_seq: 1,
          context_codepoints: 2_000,
          status: "queued",
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
    page.getByText("Checking saved refinement status…"),
  ).toBeVisible();
  await expect(
    page.getByText("Could not load refinement status: 503 API unavailable"),
  ).toBeVisible();
  await expect(
    page.getByText(
      "This sends the linked hypothesis and this recorded outcome, with up to three source metadata links, to the run’s configured AI model to draft one follow-up hypothesis. AI output may be wrong. This action does not verify the observation or change existing claims, reviews, safety decisions, or ranking.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Use outcome to refine this hypothesis",
    }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Refresh refinement status" }),
  ).toBeEnabled();
  expect(actionPosts).toBe(0);

  const getsBeforeRefresh = statusGets;
  refreshAllowed = true;
  await page.getByRole("button", { name: "Refresh refinement status" }).click();
  await expect(
    page.getByRole("button", {
      name: "Use outcome to refine this hypothesis",
    }),
  ).toBeEnabled();
  expect(statusGets).toBe(getsBeforeRefresh + 1);
  expect(actionPosts).toBe(0);

  const requestedAction = page.waitForResponse(
    (response) =>
      response
        .url()
        .includes(`/api/runs/${runId}/hypotheses/${hypothesisId}/`) &&
      response.url().endsWith(`/outcomes/${outcomeId}/refine`) &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Use outcome to refine this hypothesis" })
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
  expect(action.status).toBe("queued");
  expect(actionPosts).toBe(1);
  await expect(page.getByText("Refinement request is queued.")).toBeVisible();
});
