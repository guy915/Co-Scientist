import { readFileSync } from "node:fs";
import { createCompletedRun, expect, test } from "../support/fixtures";
import { FRONTEND_DIR, API_URL } from "../support/paths";

const policy = readFileSync(`${FRONTEND_DIR}/public/_headers`, "utf8")
  .split("Content-Security-Policy: ")[1]
  .trim();

for (const theme of ["light", "dark"]) {
  test(`production pages load under the Cloudflare CSP in ${theme}`, async ({
    page,
    api,
  }) => {
    test.setTimeout(120_000);
    const violations: string[] = [];
    const errors: string[] = [];
    const imageRequests: string[] = [];
    page.on("request", (request) => {
      if (request.url().startsWith("https://tracker.example/")) {
        imageRequests.push(request.url());
      }
    });
    page.on("console", (message) => {
      if (
        /content.security.policy|violates.*directive|refused to/i.test(
          message.text(),
        )
      ) {
        errors.push(message.text());
      }
    });
    await page.exposeFunction("recordCspViolation", (value: string) => {
      violations.push(value);
    });
    await page.addInitScript((mode) => {
      localStorage.setItem("cosci-theme", mode);
      document.addEventListener("securitypolicyviolation", (event) => {
        void (
          window as unknown as {
            recordCspViolation: (value: string) => Promise<void>;
          }
        ).recordCspViolation(
          `${event.effectiveDirective}: ${event.blockedURI}`,
        );
      });
    }, theme);
    // Exercise the SDK without sending test events to a real Sentry project.
    await page.route(
      /^https:\/\/[^/]+\.ingest(?:\.us|\.de)?\.sentry\.io\//,
      (route) => route.fulfill({ status: 200, body: "{}" }),
    );
    await page.route(/\/api\/interviews\/[^/]+$/, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      const turn = body.turns?.find(
        (item: { role: string }) => item.role === "agent",
      );
      if (turn) {
        turn.content +=
          "\n\n![S4 study diagram](https://tracker.example/pixel?private=research)";
      }
      await route.fulfill({ response, json: body });
    });
    const id = await createCompletedRun(api, {
      research_goal: "Offline CSP check of enzyme stability",
      tier: "express",
    });
    const [example] = await api.listDemoRuns();
    const routes = [
      "/",
      "/runs",
      "/runs/new",
      `/runs/${id}`,
      ...["details", "learning", "overview", "ideas"].map(
        (tab) => `/runs/${id}/${tab}`,
      ),
      `/examples/${example.id}`,
      "/privacy",
      "/terms",
      "/missing-page",
    ];
    for (const path of routes) {
      const response = await page.goto(path);
      expect(response?.headers()["content-security-policy"], path).toBe(
        policy.replace("connect-src", `connect-src ${API_URL}`),
      );
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.locator("main")).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
      if (path === "/privacy" || path === "/terms") {
        await expect(
          page.getByRole("heading", {
            name: path === "/privacy" ? "Privacy notice" : "Terms of use",
            exact: true,
          }),
        ).toBeVisible();
        await expect(
          page.getByText(
            "This text is not legal advice; the owner reviews it before launch.",
            { exact: true },
          ),
        ).toBeVisible();
        await expect(
          page.getByRole("link", { name: "guy.barel@open-coscientist.com" }),
        ).toBeAttached();
      }
      if (path.startsWith("/examples/")) {
        await expect(page).toHaveURL(/\/chats\//);
        await page.reload();
        await expect(
          page.getByLabel("Started research session"),
        ).toBeAttached();
        await expect(
          page.getByText(
            "S4 study diagram (https://tracker.example/pixel?private=research)",
          ),
        ).toBeAttached();
      }
      expect(violations, path).toEqual([]);
      expect(errors, path).toEqual([]);
      expect(imageRequests, path).toEqual([]);
    }
    for (const region of [
      "ingest.sentry.io",
      "ingest.us.sentry.io",
      "ingest.de.sentry.io",
    ]) {
      const url = `https://s4.${region}/api/0/envelope/`;
      await page.route(url, (route) =>
        route.fulfill({
          status: 200,
          body: "{}",
          headers: { "Access-Control-Allow-Origin": "*" },
        }),
      );
      const status = await page.evaluate(
        async (endpoint) =>
          (await fetch(endpoint, { method: "POST", body: "{}" })).status,
        url,
      );
      expect(status, region).toBe(200);
    }
    expect(violations).toEqual([]);
    expect(errors).toEqual([]);
  });
}
