import path from 'node:path';
import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(95);
Config.setCodec('h264');
Config.setCrf(16);
// The MD3 shape module is imported straight from the app (one source of truth
// for the landing page's shapes). That file sits outside this package, so
// webpack must also look in this package's node_modules for its `react` import.
Config.overrideWebpackConfig(config => ({
  ...config,
  resolve: {
    ...config.resolve,
    modules: [...(config.resolve?.modules ?? ['node_modules']), path.resolve('node_modules')],
  },
}));
