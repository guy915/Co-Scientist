import {defineConfig, mergeConfig} from 'vitest/config';
import viteConfig from '../../vite.config';

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      coverage: {
        provider: 'v8',
        include: ['src/**/*.{ts,tsx}'],
        exclude: [
          '**/*.test.*',
          '**/*.spec.*',
          '**/__tests__/**',
          '**/*_test_helpers.*',
          '**/*_test_support.*',
          'src/test_setup.ts',
          'src/test_fixtures.ts',
        ],
        reporter: ['text', 'json-summary'],
      },
    },
  }),
);
