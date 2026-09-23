// Copy this file next to an isolated @huggingface/transformers installation.
// Pass the frozen panel path as argv[2]; output is a JSON result on stdout.
import { readFileSync } from 'node:fs';
import { basename } from 'node:path';
import { pipeline } from '@huggingface/transformers';

const panelPath = process.argv[2];
if (!panelPath) throw new Error('Pass a frozen panel JSON path');
const panel = JSON.parse(readFileSync(panelPath, 'utf8'));
const installed = JSON.parse(readFileSync(new URL('./node_modules/@huggingface/transformers/package.json', import.meta.url), 'utf8'));
const extractor = await pipeline('feature-extraction', panel.source_model, {
  revision: panel.model_revision,
  device: 'cpu',
  dtype: 'q8',
});
const vectors = new Map();
for (const pair of panel.pairs) {
  for (const value of [pair.a, pair.b]) {
    if (vectors.has(value)) continue;
    const tensor = await extractor(value, { pooling: 'mean', normalize: true });
    vectors.set(value, Array.from(tensor.data));
  }
}
const scores = panel.pairs.map((pair) => {
  const left = vectors.get(pair.a);
  const right = vectors.get(pair.b);
  const cosine = left.reduce((sum, value, index) => sum + value * right[index], 0);
  return {
    id: pair.id,
    expected_duplicate: pair.duplicate,
    cosine: Number(cosine.toFixed(4)),
    rejected_at_source_threshold: cosine >= panel.source_threshold,
  };
});
console.log(JSON.stringify({
  panel: basename(panelPath),
  source_model: panel.source_model,
  model_revision: panel.model_revision,
  runtime: `@huggingface/transformers@${installed.version}`,
  device: 'cpu',
  dtype: 'q8',
  source_threshold: panel.source_threshold,
  inference: 'local offline; no model API or provider credentials',
  scores,
}, null, 2));
