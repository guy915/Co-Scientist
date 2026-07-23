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
// The `typescript-eslint` meta-package is the same instance gts itself uses,
// so extending its shared configs below reuses the plugin gts registers.
const tseslint = require('typescript-eslint');
const {defineConfig} = require('eslint/config');

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
  // Layer typescript-eslint strict + stylistic (non-type-checked) on top of
  // the gts baseline for application sources. These three ceilings mirror the
  // ones ruff enforces on the Python side, so a file or function that would
  // be rejected in app/ is rejected here too:
  //   complexity  - branch-heavy dispatchers belong in a lookup table, not an
  //                 if/else chain (ruff C901).
  //   max-params  - past five arguments, group the cohesive ones into a type
  //                 rather than growing the call site (ruff PLR0913).
  //   max-lines   - split by concern into sibling modules that re-export the
  //                 moved names, so import paths survive the split. Python's
  //                 side of this ceiling is checked by
  //                 evaluations/tests/test_file_length.py, which walks this
  //                 directory too; both must agree on the limit.
  {
    files: ['src/**/*.ts', 'src/**/*.tsx'],
    extends: [tseslint.configs.strict, tseslint.configs.stylistic],
    rules: {
      complexity: ['error', 5],
      'max-params': ['error', 5],
      'max-lines': ['error', {max: 500, skipBlankLines: false}],
    },
  },
  // Test files and test infrastructure: non-null assertions on queried DOM
  // nodes (e.g. `input.closest('form')!`) are idiomatic test shorthand — a
  // null simply fails the test with a clear error — and empty functions are
  // the standard way to stub no-op mocks (console spies, ResizeObserver,
  // debounce wrappers). Relaxed here at config level instead of inline
  // disables at each call site.
  {
    files: ['src/**/*.test.ts', 'src/**/*.test.tsx', 'src/test_setup.ts'],
    rules: {
      '@typescript-eslint/no-non-null-assertion': 'off',
      '@typescript-eslint/no-empty-function': 'off',
    },
  },
]);
