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
    onCloseChooser = vi.fn(),
  }: {
    route?: string;
    audience?: Audience;
    chooserOpen?: boolean;
    onCloseChooser?: () => void;
  } = {},
) {
  function Tree({open}: {open: boolean}) {
    return (
      <MemoryRouter initialEntries={[route]}>
        <AudienceProvider initialAudience={audience}>
          <AudienceGate
            onOpenAffiliation={onOpenAffiliation}
            onCloseChooser={onCloseChooser}
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

it.each(['/shared/abc123', '/access', '/proposals', '/runs/abc/details'])(
  'still asks on %s, so deep links are not a way around it',
  route => {
    const onOpen = vi.fn();
    renderGate(onOpen, {route});
    expect(onOpen).toHaveBeenCalledTimes(1);
  },
);

it('renders no markup of its own', () => {
  const {container} = renderGate(vi.fn());
  expect(container).toBeEmptyDOMElement();
});

it('commits nothing when the chooser closes unanswered', () => {
  const {setChooserOpen} = renderGate(vi.fn(), {chooserOpen: true});
  setChooserOpen(false);
  expect(window.localStorage.getItem('cosci-audience')).toBeNull();
});

it('re-opens the chooser if it closes unanswered', () => {
  const onOpen = vi.fn();
  const {setChooserOpen} = renderGate(onOpen, {chooserOpen: true});
  expect(onOpen).not.toHaveBeenCalled();
  setChooserOpen(false);
  expect(onOpen).toHaveBeenCalledTimes(1);
});

it('closes the chooser it opened once the question is answered', async () => {
  const onCloseChooser = vi.fn();
  render(
    <MemoryRouter>
      <AudienceProvider>
        <AudienceGate
          onOpenAffiliation={vi.fn()}
          onCloseChooser={onCloseChooser}
          chooserOpen={false}
        />
        <AffiliationSection />
      </AudienceProvider>
    </MemoryRouter>,
  );
  expect(onCloseChooser).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('radio', {name: /General/i}));
  expect(onCloseChooser).toHaveBeenCalledTimes(1);
});

it('leaves an answered chooser alone when it closes', () => {
  const onOpen = vi.fn();
  const {setChooserOpen} = renderGate(onOpen, {
    chooserOpen: true,
    audience: 'sbi_ucd',
  });
  setChooserOpen(false);
  expect(window.localStorage.getItem('cosci-audience')).toBe('sbi_ucd');
  expect(onOpen).not.toHaveBeenCalled();
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

  it('preselects nothing while the answer is unset', () => {
    render(
      <AudienceProvider>
        <AffiliationSection />
      </AudienceProvider>,
    );
    for (const radio of screen.getAllByRole('radio')) {
      expect(radio).not.toBeChecked();
    }
  });
});
