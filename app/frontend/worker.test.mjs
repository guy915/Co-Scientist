import assert from 'node:assert/strict';
import {test} from 'node:test';
import worker from './worker.mjs';

function assets() {
  return {
    async fetch(request) {
      const path = new URL(request.url).pathname;
      const body = path === '/index.html' ? '<main>Co-Scientist</main>' : 'asset';
      const status = ['/index.html', '/assets/app.js', '/robots.txt'].includes(path)
        ? 200
        : 404;
      return new Response(request.method === 'HEAD' ? null : body, {status});
    },
  };
}

test('deep links reload the workbench and missing bundles stay 404', async () => {
  const env = {ASSETS: assets()};
  const deepLink = await worker.fetch(
    new Request('https://open-coscientist.com/runs/private-run?tab=report'), env,
  );
  assert.equal(deepLink.status, 200);
  assert.equal(await deepLink.text(), '<main>Co-Scientist</main>');

  const missing = await worker.fetch(
    new Request('https://open-coscientist.com/assets/missing.js'), env,
  );
  assert.equal(missing.status, 404);

  for (const path of ['/assets/app.js', '/robots.txt']) {
    const response = await worker.fetch(new Request(`https://open-coscientist.com${path}`), env);
    assert.equal(await response.text(), 'asset');
  }

  const head = await worker.fetch(
    new Request('https://open-coscientist.com/chats/private-chat', {method: 'HEAD'}), env,
  );
  assert.equal(head.status, 200);
  assert.equal(await head.text(), '');
});
