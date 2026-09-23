import { createCompletedRun, expect, test } from "../support/fixtures";

test("records an outcome on an owned run and keeps it beside the report", async ({
  page,
  api,
}) => {
  const runId = await createCompletedRun(api, {
    research_goal: "Owned empirical outcome submission test",
    tier: "standard",
  });
  const requests: { method: string; clientId?: string }[] = [];
  let releaseInitialGet = () => {};
  const initialGetGate = new Promise<void>((resolve) => {
    releaseInitialGet = resolve;
  });
  await page.route(`**/api/runs/${runId}/outcomes`, async (route) => {
    requests.push({
      method: route.request().method(),
      clientId: route.request().headers()["x-client-id"],
    });
    if (route.request().method() === "GET") await initialGetGate;
    await route.continue();
  });
  await page.route(
    `**/api/runs/${runId}/hypotheses/*/outcomes`,
    async (route) => {
      const request = route.request();
      requests.push({
        method: request.method(),
        clientId: request.headers()["x-client-id"],
      });
      await route.continue();
    },
  );

  await page.goto(`/runs/${runId}/ideas`);
  await expect(
    page.getByRole("heading", { name: "Scientist-recorded observations" }),
  ).toBeVisible();
  await expect(page.getByText("Loading observations…")).toBeVisible();
  releaseInitialGet();

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
  expect(requests.length).toBeGreaterThanOrEqual(4);
  expect(requests.every((request) => request.clientId === "e2e-client")).toBe(
    true,
  );
});

test("public demo observations stay visible without a submission form", async ({
  page,
  api,
}) => {
  const demo = (await api.listDemoRuns()).find((run) =>
    /staphylococcus aureus/i.test(run.research_goal),
  );
  expect(demo).toBeTruthy();

  await page.goto(`/runs/${demo!.id}/ideas`);
  await expect(
    page.getByRole("heading", { name: "Scientist-recorded observations" }),
  ).toBeVisible();
  await expect(
    page.getByText("Public demo observations are read-only."),
  ).toBeVisible();
  expect(
    page.getByRole("group", { name: "Record an observation" }),
  ).toHaveCount(0);
});
