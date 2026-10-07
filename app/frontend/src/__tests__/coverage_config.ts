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
          'src/shared/api/testing.ts',
          'src/shared/testing/**',
        ],
        reporter: ['text', 'json-summary'],
      },
    },
  }),
);
