import type {Page} from '@playwright/test';
import {expect, test} from '../support/fixtures';

const RECORDED_ERROR = 'engine task exhausted its provider-call budget';
const BUDGET_GUIDANCE =
  'The run reached its configured model-call limit before it completed. Start a new run with a narrower research goal.';

async function routeRunFailure(
  page: Page,
  id: string,
  status: 'failed' | 'blocked',
  failureKind: string,
  error: string,
): Promise<void> {
  await page.route(`**/api/runs/${id}`, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const run = (await response.json()) as Record<string, unknown>;
    await route.fulfill({
      response,
      json: {...run, status, failure_kind: failureKind, error},
    });
  });
}

test('shows owned-run failure guidance with the recorded error after reload', async ({
  page,
  api,
}) => {
  const {id} = await api.createRun({
    research_goal: 'Offline browser test for call-budget failure guidance',
    tier: 'express',
  });
  await routeRunFailure(
    page,
    id,
    'failed',
    'llm_call_budget_exceeded',
    RECORDED_ERROR,
  );

  await page.goto(`/runs/${id}/details`);

  const guidance = page.getByRole('region', {name: 'Suggested next step'});
  await expect(guidance).toBeVisible();
  await expect(guidance).toContainText(BUDGET_GUIDANCE);
  await expect(page.getByText('Recorded error')).toBeVisible();
  await expect(page.getByText(RECORDED_ERROR, {exact: true})).toBeVisible();

  await page.reload();
  await expect(guidance).toBeVisible();
  await expect(guidance).toContainText(BUDGET_GUIDANCE);
  await expect(page.getByText(RECORDED_ERROR, {exact: true})).toBeVisible();
});

test('shows actionable guidance for the exact provider-timeout kind', async ({
  page,
  api,
}) => {
  const {id} = await api.createRun({
    research_goal: 'Offline browser test for provider-timeout guidance',
    tier: 'express',
  });
  await routeRunFailure(
    page,
    id,
    'failed',
    'llm_timeout',
    'Provider request timed out after 180 seconds',
  );

  await page.goto(`/runs/${id}/details`);

  const guidance = page.getByRole('region', {name: 'Suggested next step'});
  await expect(guidance).toBeVisible();
  await expect(guidance).toContainText(
    'The model provider did not respond within the request timeout. Try the research again later.',
  );
  await expect(
    page.getByText('Provider request timed out after 180 seconds', {
      exact: true,
    }),
  ).toBeVisible();
});

test('keeps blocked and unknown failures generic', async ({page, api}) => {
  const blocked = await api.createRun({
    research_goal: 'Offline browser test for blocked failure guidance',
    tier: 'express',
  });
  await routeRunFailure(
    page,
    blocked.id,
    'blocked',
    'llm_timeout',
    'Safety review is required',
  );

  await page.goto(`/runs/${blocked.id}/details`);
  await expect(page.getByRole('heading', {name: 'Run blocked'})).toBeVisible();
  await expect(
    page.getByRole('region', {name: 'Suggested next step'}),
  ).toHaveCount(0);
  await expect(page.getByText('Safety review is required')).toBeVisible();

  const unknown = await api.createRun({
    research_goal: 'Offline browser test for unknown failure guidance',
    tier: 'express',
  });
  await routeRunFailure(
    page,
    unknown.id,
    'failed',
    'llm_timeoutish',
    'Unclassified task error',
  );

  await page.goto(`/runs/${unknown.id}/details`);
  await expect(page.getByRole('heading', {name: 'Run failed'})).toBeVisible();
  await expect(
    page.getByRole('region', {name: 'Suggested next step'}),
  ).toHaveCount(0);
  await expect(page.getByText('Unclassified task error')).toBeVisible();
});
