import { createCompletedRun, expect, test } from "../support/fixtures";
import { E2E_RESEARCHER_ACCESS_CODE } from "../support/paths";

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
