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
  // the gts baseline for application sources.
  {
    files: ['src/**/*.ts', 'src/**/*.tsx'],
    extends: [tseslint.configs.strict, tseslint.configs.stylistic],
  },
  // Test files and test infrastructure: non-null assertions on queried DOM
  // nodes (e.g. `input.closest('form')!`) are idiomatic test shorthand — a
  // null simply fails the test with a clear error — and empty functions are
  // the standard way to stub no-op mocks (console spies, ResizeObserver,
  // debounce wrappers). Relaxed here at config level instead of inline
  // disables at each call site.
  {
    files: ['src/**/*.test.ts', 'src/**/*.test.tsx', 'src/test-setup.ts'],
    rules: {
      '@typescript-eslint/no-non-null-assertion': 'off',
      '@typescript-eslint/no-empty-function': 'off',
    },
  },
]);
