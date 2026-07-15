import {render, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {SystemStatus} from '@/api/system';
import {SystemStatusIndicator, buildSystemStatusChip} from './layout_status';

const apiMock = vi.hoisted(() => ({getSystemStatus: vi.fn()}));

vi.mock('@/api/system', () => apiMock);

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
    provider: 'mock',
    mock_mode: true,
    has_provider_key: false,
    engine_importable: true,
    model_name: 'test/model',
    supervisor_model_name: 'test/model',
    connectors: [],
    ...overrides,
  };
}

describe('buildSystemStatusChip', () => {
  it('prefers the offline chip over everything else', () => {
    const chip = buildSystemStatusChip(statusFixture(), true);
    expect(chip?.label).toBe('API offline');
    expect(chip?.danger).toBe(true);
  });

  it('flags mock mode with a neutral chip', () => {
    const chip = buildSystemStatusChip(statusFixture(), false);
    expect(chip?.label).toBe('Mock mode');
    expect(chip?.danger).toBe(false);
    expect(chip?.detail).toContain('test/model');
  });

  it('renders nothing while loading or in engine mode', () => {
    expect(buildSystemStatusChip(null, false)).toBeNull();
    expect(
      buildSystemStatusChip(
        statusFixture({mock_mode: false, provider: 'engine'}),
        false,
      ),
    ).toBeNull();
  });
});

describe('SystemStatusIndicator', () => {
  beforeEach(() => {
    apiMock.getSystemStatus.mockReset();
  });

  it('shows the Mock mode chip when /status reports mock mode', async () => {
    apiMock.getSystemStatus.mockResolvedValue(statusFixture());

    render(<SystemStatusIndicator />);

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Mock mode'),
    );
  });

  it('shows API offline when /status is unreachable', async () => {
    apiMock.getSystemStatus.mockRejectedValue(new Error('API unavailable'));

    render(<SystemStatusIndicator />);

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('API offline'),
    );
  });

  it('renders nothing for a healthy engine backend', async () => {
    apiMock.getSystemStatus.mockResolvedValue(
      statusFixture({mock_mode: false, provider: 'engine'}),
    );

    render(<SystemStatusIndicator />);

    await waitFor(() =>
      expect(apiMock.getSystemStatus).toHaveBeenCalledTimes(1),
    );
    expect(screen.queryByRole('status')).toBeNull();
  });
});
