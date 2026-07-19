import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {type Audience, AudienceProvider} from '../audience_context';
import {AudienceGate} from './audience_gate';
import {AffiliationSection} from './settings_dialog';

function renderGate(
  onOpenAffiliation: () => void,
  {
    route = '/',
    audience,
    chooserOpen = false,
  }: {route?: string; audience?: Audience; chooserOpen?: boolean} = {},
) {
  function Tree({open}: {open: boolean}) {
    return (
      <MemoryRouter initialEntries={[route]}>
        <AudienceProvider initialAudience={audience}>
          <AudienceGate
            onOpenAffiliation={onOpenAffiliation}
            chooserOpen={open}
          />
        </AudienceProvider>
      </MemoryRouter>
    );
  }
  const view = render(<Tree open={chooserOpen} />);
  return {
    ...view,
    setChooserOpen: (open: boolean) => view.rerender(<Tree open={open} />),
  };
}

describe('AudienceGate', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it('opens the affiliation settings when no audience is chosen', () => {
    const onOpen = vi.fn();
    renderGate(onOpen);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it('stays shut once an audience is chosen', () => {
    const onOpen = vi.fn();
    renderGate(onOpen, {audience: 'sbi_ucd'});
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('stays shut on the public shared-report route', () => {
    const onOpen = vi.fn();
    renderGate(onOpen, {route: '/shared/abc123'});
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('stays shut on the researcher access route', () => {
    const onOpen = vi.fn();
    renderGate(onOpen, {route: '/access'});
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('renders no markup of its own', () => {
    const {container} = renderGate(vi.fn());
    expect(container).toBeEmptyDOMElement();
  });

  it('commits the general default when the chooser is dismissed unanswered', () => {
    const {setChooserOpen} = renderGate(vi.fn(), {chooserOpen: true});
    setChooserOpen(false);
    expect(window.localStorage.getItem('cosci-audience')).toBe('general');
  });

  it('leaves an answered chooser alone when it closes', () => {
    const {setChooserOpen} = renderGate(vi.fn(), {
      chooserOpen: true,
      audience: 'sbi_ucd',
    });
    setChooserOpen(false);
    expect(window.localStorage.getItem('cosci-audience')).toBe('sbi_ucd');
  });
});

describe('AffiliationSection', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it('changes the stored audience when a new option is picked', async () => {
    render(
      <AudienceProvider>
        <AffiliationSection />
      </AudienceProvider>,
    );
    await userEvent.click(
      screen.getByRole('radio', {name: /Google AI Co-Scientist team/i}),
    );
    expect(window.localStorage.getItem('cosci-audience')).toBe('google');
  });

  it('preselects the general default while the answer is unset', () => {
    render(
      <AudienceProvider>
        <AffiliationSection />
      </AudienceProvider>,
    );
    expect(screen.getByRole('radio', {name: /General/i})).toBeChecked();
  });
});
