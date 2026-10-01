import { createCompletedRun, expect, test } from "../support/fixtures";
import {
  API_URL,
  E2E_OTHER_RESEARCHER_ACCESS_CODE,
  E2E_RESEARCHER_ACCESS_CODE,
} from "../support/paths";

test("deep links serve built assets and retain private-page metadata", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/access");
  await expect(page.getByLabel("Access code")).toBeVisible();
  const scripts = await page
    .locator("script[src]")
    .evaluateAll((elements) =>
      elements.map((element) => element.getAttribute("src") ?? ""),
    );
  expect(scripts.some((src) => /^\/assets\/.*\.js$/.test(src))).toBe(true);
  expect(
    scripts.some(
      (src) => src.includes("@vite/client") || src.includes("/src/"),
    ),
  ).toBe(false);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
    "content",
    /noindex/,
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Researcher access" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("required authentication rejects client IDs and malformed Host headers", async ({
  request,
}) => {
  for (const host of [undefined, "example.com/#", "example.com/?"]) {
    const response = await request.get(`${API_URL}/api/runs`, {
      headers: { "X-Client-ID": "e2e-client", ...(host ? { Host: host } : {}) },
    });
    expect(response.status()).toBe(401);
  }
  const response = await request.post(`${API_URL}/api/runs`, {
    data: {
      research_goal: "An unauthenticated research goal",
      tier: "express",
    },
  });
  expect(response.status()).toBe(401);
});

test("signed-in researchers can read their completed research after a reload", async ({
  page,
  api,
}) => {
  await page.goto("/access");
  await page.getByLabel("Access code").fill("invalid-test-invite");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByLabel("Access code").fill(E2E_RESEARCHER_ACCESS_CODE);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/$/);
  const token = await page.evaluate(() =>
    sessionStorage.getItem("co_scientist_access_token"),
  );
  expect(token).toBeTruthy();

  const goal = "Offline production check of enzyme stability hypotheses";
  const id = await createCompletedRun(api.asResearcher(token!), {
    research_goal: goal,
    tier: "express",
  });
  const loaded = page.waitForResponse(
    (response) =>
      response.url() === `${API_URL}/api/runs/${id}` &&
      response.status() === 200,
  );
  await page.goto(`/runs/${id}/details`);
  const read = await loaded;
  expect(read.request().headers().authorization).toBe(`Bearer ${token}`);
  expect(read.request().headers()["x-client-id"]).toBeUndefined();
  await expect(
    page.getByRole("heading", { name: /run specifications/i }),
  ).toBeVisible();
  await expect(page.getByText(goal).first()).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: /run specifications/i }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Research Overview", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /agent insights/i }),
  ).toBeVisible();

  const otherToken = await api.exchangeAccessCode(
    E2E_OTHER_RESEARCHER_ACCESS_CODE,
  );
  const otherRead = await page.request.get(`${API_URL}/api/runs/${id}`, {
    headers: { Authorization: `Bearer ${otherToken}` },
  });
  expect(otherRead.status()).toBe(404);
  const anonymousRead = await page.request.get(`${API_URL}/api/runs/${id}`);
  expect(anonymousRead.status()).toBe(401);
});
