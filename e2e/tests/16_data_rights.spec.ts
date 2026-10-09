import { execFileSync } from "node:child_process";
import { request } from "@playwright/test";
import { captureViewport, expect, test } from "../support/fixtures";
import { API_URL, VENV_PYTHON } from "../support/paths";

for (const theme of ["light", "dark"] as const) {
  for (const width of [390, 1440]) {
    test(`export and erase only this browser's data at ${width}px in ${theme}`, async ({
      page,
    }, info) => {
      const owner = `privacy-${theme}-${width}-${Date.now()}`;
      const otherOwner = `other-${owner}`;
      const ownApi = await request.newContext({
        baseURL: API_URL,
        extraHTTPHeaders: { "X-Client-ID": owner },
      });
      const otherApi = await request.newContext({
        baseURL: API_URL,
        extraHTTPHeaders: { "X-Client-ID": otherOwner },
      });
      try {
        const ownRun = await ownApi.post("/api/runs", {
          data: {
            research_goal: "Synthetic private research for export",
            tier: "express",
          },
        });
        expect(ownRun.ok()).toBe(true);
        const ownId = (await ownRun.json()).id as string;
        const otherRun = await otherApi.post("/api/runs", {
          data: { research_goal: "OTHER_OWNER_PRIVATE_GOAL", tier: "express" },
        });
        expect(otherRun.ok()).toBe(true);
        const otherId = (await otherRun.json()).id as string;
        const document = await ownApi.post("/api/documents", {
          multipart: {
            consent: "true",
            file: {
              name: "private.txt",
              mimeType: "text/plain",
              buffer: Buffer.from("SYNTHETIC_PRIVATE_DOCUMENT"),
            },
          },
        });
        expect(document.ok()).toBe(true);
        const documentId = (await document.json()).id as string;
        const interview = await ownApi.post("/api/interviews", {
          data: { research_challenge: "Synthetic private chat to export" },
        });
        expect(interview.ok()).toBe(true);
        await interview.body();
        await page.setViewportSize({ width, height: 900 });
        await page.emulateMedia({ colorScheme: theme });
        await page.goto("/");
        await page.evaluate(
          ([id, mode]) => {
            localStorage.setItem("co_scientist_client_id", id);
            localStorage.setItem("cosci-theme", mode);
            localStorage.setItem(
              "cosci-api-keys",
              JSON.stringify({ openrouter: "synthetic-private-browser-key" }),
            );
            sessionStorage.setItem(
              "co_scientist_pending_run_create:old-chat",
              "private-retry",
            );
            sessionStorage.setItem(
              "co_scientist_log_pause_until",
              String(Date.now() + 60_000),
            );
          },
          [owner, theme],
        );
        if (width <= 700)
          await page.getByRole("button", { name: "Open navigation" }).click();
        await page
          .getByRole("button", { name: "Settings", exact: true })
          .click();
        await page.getByRole("menuitem", { name: "Data", exact: true }).click();
        const dialog = page.getByRole("dialog", {
          name: "Settings",
          exact: true,
        });
        await expect(
          dialog.getByRole("heading", { name: "Your data" }),
        ).toBeVisible();
        const downloadPromise = page.waitForEvent("download");
        await dialog.getByRole("button", { name: "Export my data" }).click();
        const download = await downloadPromise;
        expect(download.suggestedFilename()).toBe("co-scientist-data.zip");
        const zipPath = info.outputPath("private-export.zip");
        await download.saveAs(zipPath);
        const exported = JSON.parse(
          execFileSync(
            VENV_PYTHON,
            [
              "-c",
              "import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps({n:json.loads(z.read(n)) for n in z.namelist()}))",
              zipPath,
            ],
            { encoding: "utf8" },
          ),
        );
        const content = JSON.stringify(exported);
        expect(content).toContain(ownId);
        expect(content).toContain(documentId);
        expect(content).toContain("SYNTHETIC_PRIVATE_DOCUMENT");
        expect(content).toContain("Synthetic private chat to export");
        expect(exported["settings.json"].theme).toBe(theme);
        expect(content).not.toContain(otherId);
        expect(content).not.toContain(otherOwner);
        expect(content).not.toContain("OTHER_OWNER_PRIVATE_GOAL");
        expect(content).not.toContain("synthetic-private-browser-key");
        const otherTab = await page.context().newPage();
        await otherTab.goto(`/runs/${ownId}/overview`);
        await otherTab.evaluate(() => {
          sessionStorage.setItem(
            "co_scientist_pending_run_create:other-tab",
            "private-retry",
          );
          sessionStorage.setItem(
            "co_scientist_log_pause_until",
            String(Date.now() + 60_000),
          );
        });
        const erase = dialog.getByRole("button", {
          name: "Delete all my data",
        });
        await expect(erase).toBeDisabled();
        await dialog.getByLabel("Type DELETE to confirm").fill("DELETE");
        await expect(erase).toBeEnabled();
        await captureViewport(page, {
          width,
          height: 900,
          name: `data-rights-${width}-${theme}.png`,
        });
        const deletion = page.waitForResponse(
          (response) =>
            response.url().endsWith("/api/data/delete") &&
            response.request().method() === "POST",
        );
        await erase.click();
        expect((await deletion).status()).toBe(200);
        await expect(dialog).toHaveCount(0);
        await expect(otherTab).toHaveURL(/\/$/);
        expect(
          await otherTab.evaluate(() =>
            sessionStorage.getItem("co_scientist_pending_run_create:other-tab"),
          ),
        ).toBeNull();
        expect(
          await otherTab.evaluate(() =>
            sessionStorage.getItem("co_scientist_log_pause_until"),
          ),
        ).toBeNull();
        await otherTab.close();
        await expect
          .poll(async () =>
            page.evaluate(() => localStorage.getItem("cosci-api-keys")),
          )
          .toBeNull();
        expect(
          await page.evaluate(() =>
            sessionStorage.getItem("co_scientist_pending_run_create:old-chat"),
          ),
        ).toBeNull();
        expect(
          await page.evaluate(() =>
            sessionStorage.getItem("co_scientist_log_pause_until"),
          ),
        ).toBeNull();
        expect((await ownApi.get(`/api/runs/${ownId}`)).status()).toBe(404);
        expect(await (await ownApi.get("/api/interviews")).json()).toEqual([]);
        expect((await otherApi.get(`/api/runs/${otherId}`)).status()).toBe(200);
        expect(
          (await ownApi.post("/api/data/export", { data: {} })).status(),
        ).toBe(410);
      } finally {
        await ownApi.dispose();
        await otherApi.dispose();
      }
    });
  }
}
