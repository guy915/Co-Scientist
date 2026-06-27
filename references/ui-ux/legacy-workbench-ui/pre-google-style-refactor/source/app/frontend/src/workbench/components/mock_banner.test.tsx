import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen} from '@testing-library/react';
import type {SystemStatus} from '@/api/runs';
import {MockBanner} from './mock_banner';

const getSystemStatus = vi.fn<() => Promise<SystemStatus>>();

vi.mock('@/api/runs', () => ({
  getSystemStatus: () => getSystemStatus(),
}));

/** Builds a complete SystemStatus, overriding only the fields under test. */
function makeStatus(overrides: Partial<SystemStatus>): SystemStatus {
  return {
    mcp_available: false,
    pubmed_available: false,
    literature_review_available: false,
    mcp_server_url: '',
    provider: 'engine',
    mock_mode: false,
    has_provider_key: true,
    engine_importable: true,
    model_name: 'test-model',
    ...overrides,
  };
}

describe('MockBanner', () => {
  beforeEach(() => {
    getSystemStatus.mockReset();
  });

  it('renders the live engine banner when not in mock mode', async () => {
    getSystemStatus.mockResolvedValue(
      makeStatus({
        mock_mode: false,
        provider: 'engine',
        model_name: 'deepseek/deepseek-chat',
      }),
    );
    render(<MockBanner />);
    expect(await screen.findByText(/Live engine mode/)).toBeInTheDocument();
    expect(screen.getByText('deepseek/deepseek-chat')).toBeInTheDocument();
  });

  it('renders the mock-mode warning when in mock mode', async () => {
    getSystemStatus.mockResolvedValue(makeStatus({mock_mode: true}));
    render(<MockBanner />);
    expect(await screen.findByText('Mock Mode')).toBeInTheDocument();
  });
});
