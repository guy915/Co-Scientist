import AxeBuilder from "@axe-core/playwright";
import {
  assertNoHorizontalOverflow,
  captureViewport,
  expect,
  test,
} from "../support/fixtures";

for (const theme of ["light", "dark"]) {
  for (const width of [390, 1440]) {
    for (const kind of ["privacy", "terms"]) {
      test(`${kind} is public at ${width}px in ${theme}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.addInitScript(
          (mode) => localStorage.setItem("cosci-theme", mode),
          theme,
        );
        await page.goto(`/${kind}`);
        await expect(
          page.getByRole("heading", {
            name: kind === "privacy" ? "Privacy notice" : "Terms of use",
            exact: true,
          }),
        ).toBeVisible();
        await expect(
          page.getByText(
            "This text is not legal advice; the owner reviews it before launch.",
          ),
        ).toBeVisible();
        await expect(
          page
            .getByRole("link", { name: "guy.barel@open-coscientist.com" })
            .first(),
        ).toHaveAttribute("href", "mailto:guy.barel@open-coscientist.com");
        await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
          "content",
          "index, follow",
        );
        await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
          "href",
          `https://open-coscientist.com/${kind}`,
        );
        await assertNoHorizontalOverflow(page, width);
        await captureViewport(page, {
          width,
          height: 900,
          name: `${kind}-${width}-${theme}.png`,
        });
        await page.reload();
        await expect(page.getByRole("article")).toBeVisible();
        await page
          .getByRole("navigation", { name: "Legal pages" })
          .getByRole("link", { name: "Research workspace" })
          .click();
        await expect(page.getByRole("textbox").first()).toBeVisible();
        await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
          "content",
          "noindex, nofollow",
        );
      });
    }
  }
}

test("landing footer links to both notices and sitemap lists them", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Scroll to see how Open Co-Scientist works" })
    .click();
  const footer = page.getByRole("navigation", { name: "Legal information" });
  await footer.scrollIntoViewIfNeeded();
  await expect(footer.locator("..")).toHaveJSProperty("tagName", "FOOTER");
  const audit = await new AxeBuilder({ page })
    .withRules(["landmark-contentinfo-is-top-level"])
    .analyze();
  expect(audit.violations).toEqual([]);
  await expect(
    footer.getByRole("link", { name: "Privacy notice" }),
  ).toHaveAttribute("href", "/privacy");
  await expect(
    footer.getByRole("link", { name: "Terms of use" }),
  ).toHaveAttribute("href", "/terms");
  await footer.getByRole("link", { name: "Privacy notice" }).click();
  await expect(
    page.getByRole("heading", { name: "Privacy notice", exact: true }),
  ).toBeVisible();
  const sitemap = await request.get("/sitemap.xml");
  expect(sitemap.status()).toBe(200);
  expect(await sitemap.text()).toContain(
    "https://open-coscientist.com/privacy",
  );
  expect(await sitemap.text()).toContain("https://open-coscientist.com/terms");
});
