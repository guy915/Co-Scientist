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

it('does not re-open a chooser the user closed unanswered', () => {
  const onOpen = vi.fn();
  const {setChooserOpen} = renderGate(onOpen, {chooserOpen: true});
  expect(onOpen).not.toHaveBeenCalled();
  setChooserOpen(false);
  // The question was already put this page load; re-opening it here would
  // fight the user's dismissal (and their move to another Settings section,
  // which leaves the Affiliation section the same way).
  expect(onOpen).not.toHaveBeenCalled();
});

it('asks once, not again after its own chooser is dismissed', () => {
  const onOpen = vi.fn();
  const {setChooserOpen} = renderGate(onOpen);
  expect(onOpen).toHaveBeenCalledTimes(1);
  setChooserOpen(true);
  setChooserOpen(false);
  expect(onOpen).toHaveBeenCalledTimes(1);
});

it('leaves a self-opened Settings dialog alone once the gate is dismissed', async () => {
  const onCloseChooser = vi.fn();
  function Tree({open}: {open: boolean}) {
    return (
      <MemoryRouter>
        <AudienceProvider>
          <AudienceGate
            onOpenAffiliation={vi.fn()}
            onCloseChooser={onCloseChooser}
            chooserOpen={open}
          />
          <AffiliationSection />
        </AudienceProvider>
      </MemoryRouter>
    );
  }
  const view = render(<Tree open={false} />);
  view.rerender(<Tree open={true} />); // the gate's own chooser opens
  view.rerender(<Tree open={false} />); // the user closes it unanswered
  view.rerender(<Tree open={true} />); // and later opens Settings themselves
  // Answering in the dialog they opened must not tear it down under them.
  await userEvent.click(screen.getByRole('radio', {name: /General/i}));
  expect(onCloseChooser).not.toHaveBeenCalled();
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
