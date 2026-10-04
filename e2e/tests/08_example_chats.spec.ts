import {captureViewport, expect, test} from '../support/fixtures';

for (const theme of ['light', 'dark']) {
  test(`examples open as full private chats and keep chatting on a phone in ${theme}`, async ({
    page,
    api,
  }) => {
    await page.setViewportSize({width: 375, height: 812});
    await page.addInitScript(
      mode => localStorage.setItem('cosci-theme', mode),
      theme,
    );
    const demos = await api.listDemoRuns();
    await page.goto('/');
    const examples = page.getByRole('navigation', {name: 'Example chats'});
    await expect(examples).toBeInViewport();
    await expect(examples.getByRole('link')).toHaveCount(3);
    await expect(page.getByRole('textbox')).toBeInViewport();
    await captureViewport(page, {
      width: 375,
      height: 812,
      name: `examples-home-${theme}.png`,
    });
    await examples.locator(`a[href="/examples/${demos[0].id}"]`).click();
    await expect(page).toHaveURL(/\/chats\//);
    const chatUrl = page.url();
    await expect(page.getByLabel('Inferred run setup')).toBeAttached();
    await expect(page.getByLabel('Started research session')).toBeAttached();
    await expect(
      page.getByRole('link', {name: 'View session details'}),
    ).toBeAttached();
    const question = `Which controls need replication in this ${theme} example?`;
    const composer = page.getByRole('textbox', {
      name: 'Ask a question about this research session',
    });
    await expect(composer).toBeInViewport();
    await composer.fill(question);
    await page.getByRole('button', {name: 'Send', exact: true}).click();
    await expect(
      page
        .getByText("Answering from this run's own artifacts", {
          exact: false,
        })
        .last(),
    ).toBeVisible();
    await expect(
      page.getByRole('button', {name: 'Send', exact: true}),
    ).toBeVisible();
    await page.reload();
    await expect(page.getByText(question, {exact: true})).toBeAttached();
    await expect(composer).toBeInViewport();
    await page.goto(`/examples/${demos[0].id}`);
    await expect(page).toHaveURL(chatUrl);
    await expect(page.getByText(question, {exact: true})).toBeAttached();
    await captureViewport(page, {
      width: 375,
      height: 812,
      name: `example-chat-${theme}.png`,
    });
  });
}

test('every curated example carries its conversation, saved plan and linked results', async ({
  page,
  api,
}) => {
  const demos = await api.listDemoRuns();
  for (const example of demos) {
    await page.goto(`/examples/${example.id}`);
    await expect(page).toHaveURL(/\/chats\//);
    const plan = page.getByLabel('Inferred run setup');
    await expect(plan).toBeAttached();
    await expect(plan.getByRole('radio', {name: /Standard/})).toBeChecked();
    await expect(
      page.getByText(
        'This is a curated example conversation and research plan.',
        {exact: false},
      ),
    ).toBeAttached();
    await expect(
      page.getByRole('link', {name: 'View session details'}),
    ).toBeAttached();
    await expect(
      page.getByRole('textbox', {
        name: 'Ask a question about this research session',
      }),
    ).toBeVisible();
    await page.getByRole('link', {name: 'View session details'}).click();
    await expect(page).toHaveURL(/\/runs\/.*\/details/);
    await expect(
      page.getByRole('heading', {name: /^Example: /, level: 1}),
    ).toBeVisible();
  }
});
