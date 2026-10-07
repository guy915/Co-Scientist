import * as Sentry from '@sentry/browser';
import {getStoredApiKey, keyedProviders} from './client_id';

const CLIENT_ID_KEY = 'co_scientist_client_id';
const MIN_SECRET_LENGTH = 8;

// The client ID is the run-ownership capability and saved provider keys are
// credentials; neither may leave in an error report.
function browserSecrets(): string[] {
  try {
    const secrets = keyedProviders().map(provider => getStoredApiKey(provider));
    secrets.push(window.localStorage.getItem(CLIENT_ID_KEY) ?? '');
    return secrets.filter(secret => secret.length >= MIN_SECRET_LENGTH);
  } catch {
    return [];
  }
}

export function scrubSecrets<T>(value: T, secrets: readonly string[]): T {
  if (typeof value === 'string') {
    let text: string = value;
    for (const secret of secrets) {
      text = text.split(secret).join('[REDACTED]');
    }
    return text as T;
  }
  if (Array.isArray(value)) {
    return value.map(item => scrubSecrets(item, secrets)) as T;
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        scrubSecrets(item, secrets),
      ]),
    ) as T;
  }
  return value;
}

export function initErrorTracking(dsn: string): void {
  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    sendDefaultPii: false,
    // Console messages can carry research text; network and navigation
    // breadcrumbs keep only URLs and status codes.
    beforeBreadcrumb: breadcrumb =>
      breadcrumb.category === 'console' ? null : breadcrumb,
    beforeSend: event => scrubSecrets(event, browserSecrets()),
  });
}
