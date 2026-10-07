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

const HEX_COLOR = String.raw`/#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/`;
const FUNCTION_COLOR = String.raw`/\b(rgba?|hsla?)\(/`;
const ARBITRARY_RADIUS = String.raw`/rounded(-[a-z]{1,2})?-\[|border-radius:/`;

function uiBuildingBlockRules() {
  const inText = (pattern, message) => [
    {selector: `Literal[value=${pattern}]`, message},
    {selector: `TemplateElement[value.raw=${pattern}]`, message},
  ];
  return [
    {
      selector: "JSXOpeningElement[name.name='button']",
      message:
        'Use Button, IconButton or another control from @/shared/ui instead of a raw <button>.',
    },
    ...inText(
      HEX_COLOR,
      'Use a theme token instead of a hex colour (styles/tokens.css).',
    ),
    ...inText(
      FUNCTION_COLOR,
      'Use a theme token instead of an rgb()/hsl() colour (styles/tokens.css).',
    ),
    ...inText(
      ARBITRARY_RADIUS,
      'Use a radius from the scale or a named radius token instead of an arbitrary radius.',
    ),
    {
      selector: "Property[key.name='borderRadius']",
      message:
        'Use a radius from the scale or a named radius token instead of an inline radius.',
    },
  ];
}

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
  // Shape, colour and focus belong to src/shared/ui (app/AGENTS.md, "UI
  // building blocks"). Screens compose those components and theme tokens.
  {
    files: ['src/**/*.ts', 'src/**/*.tsx'],
    ignores: [
      'src/shared/ui/**',
      'src/**/*.test.ts',
      'src/**/*.test.tsx',
      // Derives the Material palette tokens at runtime.
      'src/workbench/md3_scheme.ts',
    ],
    rules: {
      'no-restricted-syntax': ['error', ...uiBuildingBlockRules()],
    },
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
