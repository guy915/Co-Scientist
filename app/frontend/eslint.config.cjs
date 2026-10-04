/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
// GTS registers the TypeScript plugin and parser. Reuse those when layering
// strict rules: dependency layouts may resolve a second plugin instance.
const tseslint = require('typescript-eslint');
const {defineConfig} = require('eslint/config');
const strictRules = tseslint.configs.strict.filter(
  config => config.name !== 'typescript-eslint/base',
);
const stylisticRules = tseslint.configs.stylistic.filter(
  config => config.name !== 'typescript-eslint/base',
);

module.exports = defineConfig([
  {
    ignores: [
      '**/node_modules/**',
      '**/dist/**',
      '.vercel/**',
      'scripts/**',
      'eslint.config.cjs',
      '.prettierrc.cjs',
      'vite.config.ts',
    ],
  },
  ...require('gts'),
  // Size ceilings force unrelated helpers and facades out of cohesive modules.
  {
    files: ['src/**/*.ts', 'src/**/*.tsx'],
    extends: [...strictRules, ...stylisticRules],
  },
  // Test null assertions fail clearly; empty functions are intentional mocks.
  // Configure these once rather than requiring disables at every test call.
  {
    files: ['src/**/*.test.ts', 'src/**/*.test.tsx', 'src/test_setup.ts'],
    rules: {
      '@typescript-eslint/no-non-null-assertion': 'off',
      '@typescript-eslint/no-empty-function': 'off',
    },
  },
]);
