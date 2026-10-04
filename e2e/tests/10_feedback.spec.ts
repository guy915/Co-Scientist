import {captureViewport, CLIENT_ID, expect, test} from '../support/fixtures';
import {API_URL, E2E_LOGS_ADMIN_TOKEN} from '../support/paths';

for (const theme of ['light', 'dark']) {
  for (const width of [1440, 375]) {
    test(`feedback silently attaches session diagnostics at ${width}px in ${theme}`, async ({
      page,
      api,
    }) => {
      await page.setViewportSize({width, height: 812});
      await page.addInitScript(
        mode => localStorage.setItem('cosci-theme', mode),
        theme,
      );
      await page.route('https://www.youtube-nocookie.com/**', route =>
        route.fulfill({body: '<html>Trailer</html>', contentType: 'text/html'}),
      );
      await page.goto('/');
      const header = page.locator('.ucs-header-action-bar');
      const feedback = header.getByRole('button', {
        name: 'Feedback',
        exact: true,
      });
      const logs = header.getByRole('button', {name: /^Logs/});
      await expect(feedback).toBeInViewport();
      await expect(logs).toBeInViewport();
      const feedbackBox = await feedback.boundingBox();
      const logsBox = await logs.boundingBox();
      expect(feedbackBox!.x + feedbackBox!.width).toBeLessThanOrEqual(
        logsBox!.x,
      );
      await feedback.click();
      let dialog = page.getByRole('dialog', {name: 'Feedback', exact: true});
      await expect(dialog.getByLabel('Message')).toBeFocused();
      await expect(
        dialog.getByRole('button', {name: 'Submit', exact: true}),
      ).toBeDisabled();
      expect(
        await dialog.getByLabel('Category').locator('option').allTextContents(),
      ).toEqual([
        'Bug',
        'Security',
        'Results quality',
        'Feature request',
        'Other',
      ]);
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      await expect(feedback).toBeFocused();
      const examples = await api.listDemoRuns();
      await page.goto(`/examples/${examples[0].id}`);
      await expect(page).toHaveURL(/\/chats\//);
      const linkedRun = await page
        .getByRole('link', {name: 'View session details'})
        .getAttribute('href');
      const runId = linkedRun!.split('/')[2];
      await feedback.click();
      dialog = page.getByRole('dialog', {name: 'Feedback', exact: true});
      await expect(dialog.getByLabel('Message')).toBeFocused();
      const box = await dialog.boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.y + box!.height).toBeLessThanOrEqual(812);
      expect(box!.x + box!.width / 2).toBeCloseTo(width / 2, 0);
      const message = `Feedback browser verification ${theme} ${width}`;
      await dialog.getByLabel('Category').selectOption('Results quality');
      await dialog.getByLabel('Message').fill(message);
      await expect(dialog.getByText(/diagnostic|logs|attach/i)).toHaveCount(0);
      await captureViewport(page, {
        width,
        height: 812,
        name: `feedback-${theme}-${width}.png`,
      });
      const submitted = page.waitForResponse(
        response =>
          response.url().endsWith('/api/feedback') &&
          response.request().method() === 'POST',
      );
      await dialog.getByRole('button', {name: 'Submit', exact: true}).click();
      expect((await submitted).status()).toBe(201);
      await expect(dialog).toHaveCount(0);
      expect(
        (await page.request.get(`${API_URL}/api/feedback/admin`)).status(),
      ).toBe(403);
      const admin = await page.request.get(`${API_URL}/api/feedback/admin`, {
        headers: {'X-Logs-Token': E2E_LOGS_ADMIN_TOKEN},
      });
      expect(admin.status()).toBe(200);
      const rows = (await admin.json()).feedback as {
        message: string;
        category: string;
        client_id: string;
        url: string;
        run_id: string;
        diagnostics: string;
      }[];
      const row = rows.find(record => record.message === message)!;
      expect(row.client_id).toBe(CLIENT_ID);
      expect(row.category).toBe('Results quality');
      expect(row.run_id).toBe(runId);
      expect(row.url).toBe(page.url());
      for (const marker of [
        '=== ABOUT THESE DIAGNOSTIC LOGS ===',
        '=== SESSION DETAILS ===',
        '=== STATISTICS (loaded window) ===',
        '=== LOGS (JSON) ===',
      ])
        expect(row.diagnostics).toContain(marker);
      expect(row.diagnostics).toContain('modal_open: Feedback');
      await logs.click();
      await expect(
        page.getByRole('button', {name: 'Copy', exact: true}),
      ).toBeVisible();
      await expect(
        page.getByRole('button', {name: 'Clear', exact: true}),
      ).toBeVisible();
    });
  }
}
