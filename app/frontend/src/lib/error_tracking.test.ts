import {afterEach, describe, expect, it, vi} from 'vitest';

const init = vi.hoisted(() => vi.fn());
vi.mock('@sentry/browser', () => ({init}));

import {setStoredApiKey} from './client_id';
import {initErrorTracking, scrubSecrets} from './error_tracking';

interface Options {
  sendDefaultPii: boolean;
  beforeBreadcrumb: (breadcrumb: {category?: string}) => unknown;
  beforeSend: (event: unknown) => unknown;
}

describe('error tracking', () => {
  afterEach(() => {
    localStorage.clear();
    init.mockReset();
  });

  it('redacts secrets in nested report strings', () => {
    const event = {
      message: 'failed for client-abc12345',
      exception: {values: [{value: 'key sk-secret-1 rejected'}]},
    };

    expect(scrubSecrets(event, ['client-abc12345', 'sk-secret-1'])).toEqual({
      message: 'failed for [REDACTED]',
      exception: {values: [{value: 'key [REDACTED] rejected'}]},
    });
  });

  it('sends no PII, drops console breadcrumbs and scrubs stored keys', () => {
    localStorage.setItem('co_scientist_client_id', 'client-owner-capability');
    setStoredApiKey('sk-stored-provider-key', 'deepseek');

    initErrorTracking('https://key@sentry.example/1');

    const options = init.mock.calls[0][0] as Options;
    expect(options.sendDefaultPii).toBe(false);
    expect(options.beforeBreadcrumb({category: 'console'})).toBeNull();
    expect(options.beforeBreadcrumb({category: 'fetch'})).toEqual({
      category: 'fetch',
    });
    expect(
      options.beforeSend({
        message: 'client-owner-capability used sk-stored-provider-key',
      }),
    ).toEqual({message: '[REDACTED] used [REDACTED]'});
  });
});
