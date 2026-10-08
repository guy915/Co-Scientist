import { expect, test } from "../support/fixtures";

for (const theme of ["light", "dark"]) {
  test(`YouTube is contacted only after an explicit click in ${theme}`, async ({
    page,
    context,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript(
      (mode) => localStorage.setItem("cosci-theme", mode),
      theme,
    );
    const googleRequests: string[] = [];
    await context.route(
      /https:\/\/(?:[^/]+\.)?(?:youtube\.com|youtube-nocookie\.com|google\.com|googlevideo\.com|ytimg\.com)\//,
      (route) => {
        googleRequests.push(route.request().url());
        return route.fulfill({
          contentType: "text/html",
          body: "<p>External trailer</p>",
        });
      },
    );
    await page.goto("/");
    await page
      .getByRole("button", {
        name: "Scroll to see how Open Co-Scientist works",
      })
      .click();
    const link = page.getByRole("link", {
      name: "Watch the trailer on YouTube",
    });
    await link.scrollIntoViewIfNeeded();
    await expect(link).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(googleRequests).toEqual([]);
    await expect(page.locator("iframe")).toHaveCount(0);
    expect(await context.cookies()).toEqual([]);
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    const popupPromise = page.waitForEvent("popup");
    await link.click();
    const popup = await popupPromise;
    await popup.waitForLoadState("domcontentloaded");
    expect(googleRequests).toEqual([
      "https://www.youtube.com/watch?v=Wnhe8a8kKc0",
    ]);
    await popup.close();
  });
}
