import {render, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {SystemStatus} from '@/api/system';
import {SystemStatusIndicator} from './layout_header';

const apiMock = vi.hoisted(() => ({getSystemStatus: vi.fn()}));

vi.mock('@/api/system', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/system')>()),
  ...apiMock,
}));

function statusFixture(overrides: Partial<SystemStatus> = {}): SystemStatus {
  return {
    mcp_available: false,
    pubmed_available: false,
    literature_review_available: false,
    probes: {
      mcp: {state: 'down', error: null},
      pubmed: {state: 'down', error: null},
    },
    mcp_server_url: '',
    provider: 'engine',
    llm_backend: 'offline',
    has_provider_key: false,
    engine_importable: true,
    model_name: 'test/model',
    supervisor_model_name: 'test/model',
    connectors: [],
    ...overrides,
  };
}

describe('SystemStatusIndicator', () => {
  beforeEach(() => {
    apiMock.getSystemStatus.mockReset();
  });

  it('shows the Offline mode chip when /status reports offline', async () => {
    apiMock.getSystemStatus.mockResolvedValue(statusFixture());

    render(<SystemStatusIndicator />);

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Offline mode'),
    );
  });

  it('shows API offline when /status is unreachable', async () => {
    apiMock.getSystemStatus.mockRejectedValue(new Error('API unavailable'));

    render(<SystemStatusIndicator />);

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('API offline'),
    );
  });
});
