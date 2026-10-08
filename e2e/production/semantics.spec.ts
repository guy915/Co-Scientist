import { writeFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "../support/fixtures";
import { tabTo } from "../support/keyboard";

for (const theme of ["light", "dark"]) {
  test(`@keyboard-semantics header landmark and conversation heading ${theme}`, async ({
    page,
  }, info) => {
    await page.addInitScript(
      (mode) => localStorage.setItem("cosci-theme", mode),
      theme,
    );
    await page.goto("/");
    const banner = page.getByRole("banner", { name: "Workspace header" });
    await expect.soft(banner).toHaveCount(1);
    if (await banner.count()) {
      await expect(
        banner.getByRole("button", { name: "Feedback", exact: true }),
      ).toBeVisible();
      await expect(banner.getByRole("link", { name: /home/ })).toBeVisible();
    }
    const composer = page.getByRole("textbox").last();
    await tabTo(page, composer);
    await page.keyboard.insertText("Compare mechanisms of enzyme stability.");
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("button", { name: "Copy response" }).first(),
    ).toBeVisible();
    const heading = page.getByRole("heading", { level: 1 });
    await expect.soft(heading).toHaveCount(1);
    if (await heading.count()) await expect(heading).not.toBeEmpty();
    const results = await new AxeBuilder({ page })
      .withRules(["region", "page-has-heading-one"])
      .analyze();
    expect.soft(results.violations).toEqual([]);
    const tree = info.outputPath("semantics.yml");
    await writeFile(tree, await page.locator("body").ariaSnapshot());
    await info.attach("semantics-tree", {
      path: tree,
      contentType: "text/yaml",
    });
    const screenshot = info.outputPath("semantics.png");
    await page.screenshot({ path: screenshot });
    await info.attach("semantics", {
      path: screenshot,
      contentType: "image/png",
    });
  });
}
