import {createCompletedRun, expect, test} from '../support/fixtures';
import {API_URL, E2E_RESEARCHER_ACCESS_CODE} from '../support/paths';

test('saved refinement stays visible in active and failed runs', async ({
  page,
  api,
}) => {
  const token = await api.exchangeAccessCode(E2E_RESEARCHER_ACCESS_CODE);
  const researcherApi = api.asResearcher(token);
  const runId = await createCompletedRun(researcherApi, {
    research_goal: 'Offline outcome-refinement status test',
    tier: 'standard',
  });
  const headers = {Authorization: `Bearer ${token}`};
  const hypothesesResponse = await page.request.get(
    `${API_URL}/api/runs/${runId}/hypotheses`,
    {headers},
  );
  expect(hypothesesResponse.status()).toBe(200);
  const hypotheses = (await hypothesesResponse.json()) as {
    hypotheses: {id: string}[];
  };
  const hypothesisId = hypotheses.hypotheses[0]?.id;
  expect(hypothesisId).toBeTruthy();
  const outcomeResponse = await page.request.post(
    `${API_URL}/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes`,
    {
      headers,
      data: {
        method_protocol: 'Density-gradient centrifugation',
        conditions: 'One generation in light nitrogen',
        measured_observation: 'One intermediate-density band',
        units: 'band density',
        controls: 'Heavy and light references',
        interpretation: 'Consistent with semiconservative replication',
        referenced_evidence_ids: [],
      },
    },
  );
  expect(outcomeResponse.status(), await outcomeResponse.text()).toBe(201);
  const outcomeId = ((await outcomeResponse.json()) as {id: string}).id;

  await page.addInitScript(
    accessToken => sessionStorage.setItem('co_scientist_access_token', accessToken),
    token,
  );
  let visibleRunStatus = 'running';
  await page.route(`**/api/runs/${runId}`, async route => {
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown>;
    await route.fulfill({response, json: {...body, status: visibleRunStatus}});
  });
  await page.route(
    `**/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes/${outcomeId}/refine`,
    route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          action_id: 'saved-refinement',
          run_id: runId,
          hypothesis_id: hypothesisId,
          outcome_id: outcomeId,
          task_idempotency_key: 'outcome-refinement:saved-refinement',
          checkpoint_seq: 1,
          context_codepoints: 100,
          status: visibleRunStatus === 'failed' ? 'failed' : 'running',
          child_hypothesis_id: null,
          created_at: 1_700_000_000,
          replayed: true,
        }),
      }),
  );

  await page.goto(`/runs/${runId}/ideas`);
  await expect(page.getByText('Refinement is running.')).toBeVisible();
  visibleRunStatus = 'failed';
  await page.reload();
  await expect(
    page.getByText('Refinement failed and remains available for owner retry.'),
  ).toBeVisible();
  await expect(
    page.getByRole('button', {name: /retry refinement/i}),
  ).toBeVisible();
});
