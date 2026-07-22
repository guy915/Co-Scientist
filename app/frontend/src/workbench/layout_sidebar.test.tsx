import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  apiMock,
  installLayoutMocks,
  renderLayout,
  runFixture,
} from './layout_test_support';

beforeEach(() => {
  installLayoutMocks();
});

/** Renders the layout with twelve real runs feeding the sidebar chat list. */
function renderTwelveSidebarChats() {
  apiMock.listDemoRuns.mockResolvedValue([]);
  apiMock.listRuns.mockResolvedValue(
    Array.from({length: 12}, (_, index) =>
      runFixture(
        `run-${index + 1}`,
        `Very long sidebar research question ${index + 1}`,
      ),
    ),
  );
  renderLayout();
}

it('toggles the Co-Scientist sidebar from the menu button', async () => {
  const {container} = renderLayout();

  // Collapsed icon rail by default, matching the reference product.
  const menu = screen.getByRole('button', {name: 'Menu'});
  expect(menu).toHaveAttribute('aria-expanded', 'false');
  expect(menu).toHaveTextContent('Menu');
  expect(container.querySelector('.ucs-app-shell')).toHaveClass(
    'nav-collapsed',
  );

  fireEvent.click(menu);

  expect(menu).toHaveAttribute('aria-expanded', 'true');
  expect(container.querySelector('.ucs-app-shell')).toHaveClass('nav-open');

  fireEvent.click(menu);

  expect(menu).toHaveAttribute('aria-expanded', 'false');
  expect(container.querySelector('.ucs-app-shell')).toHaveClass(
    'nav-collapsed',
  );
});

it('keeps only Co-Scientist navigation and real chat history', async () => {
  renderLayout();

  expect(screen.queryByRole('button', {name: 'Library'})).toBeNull();
  expect(screen.queryByRole('button', {name: 'Skills'})).toBeNull();
  expect(screen.queryByText('Agents')).toBeNull();
  expect(screen.queryByText('Deep Research')).toBeNull();
  expect(screen.queryByText('NotebookLM')).toBeNull();
  expect(screen.queryByLabelText('Switch to Gemini app')).toBeNull();
  expect(screen.getByRole('button', {name: /Logs 0/i})).toBeInTheDocument();

  expect(await screen.findByText('Chats')).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByRole('link', {name: /ferroptosis/i})).toHaveAttribute(
      'href',
      '/runs/demo-ferroptosis/details',
    );
  });

  const newChat = screen.getByRole('button', {name: 'New chat'});
  expect(newChat).toHaveAttribute('data-tooltip', 'New chat');
  expect(newChat).toHaveClass('ucs-tooltip-anchor');
  expect(newChat).toHaveClass('ucs-tooltip-right');

  // The non-functional "Search" nav item was removed.
  expect(screen.queryByRole('button', {name: 'Search'})).toBeNull();

  const chat = screen.getByRole('link', {name: /ferroptosis/i});
  expect(chat).not.toHaveAttribute('title');
  expect(chat.getAttribute('data-tooltip')).toMatch(
    /ferroptosis in pancreatic cancer cells/i,
  );
  expect(chat).toHaveClass('ucs-tooltip-wrap');
});

it('shows the generated session title in sidebar chats', async () => {
  apiMock.listDemoRuns.mockResolvedValue([]);
  apiMock.listRuns.mockResolvedValue([
    {
      ...runFixture(
        'run-titled',
        'Generate testable hypotheses for ferroptosis in pancreatic cancer cells.',
      ),
      title: 'Ferroptosis in pancreatic cancer',
    },
  ]);

  renderLayout();

  // The sidebar link renders the model-generated title, not a clause of the
  // raw research goal, matching the recents cards.
  const chat = await screen.findByRole('link', {
    name: 'Ferroptosis in pancreatic cancer',
  });
  expect(chat).toHaveAttribute('href', '/runs/run-titled/details');
  // The full research goal still rides along as the hover tooltip.
  expect(chat.getAttribute('data-tooltip')).toMatch(
    /Generate testable hypotheses for ferroptosis/i,
  );
});

it('shows ten sidebar chats before expanding the rest', async () => {
  renderTwelveSidebarChats();

  expect(
    await screen.findByRole('link', {
      name: /Very long sidebar research question 10/i,
    }),
  ).toHaveAttribute('data-tooltip', 'Very long sidebar research question 10');
  expect(
    screen.queryByRole('link', {
      name: /Very long sidebar research question 11/i,
    }),
  ).toBeNull();

  fireEvent.click(screen.getByRole('button', {name: 'Show more'}));

  expect(
    screen.getByRole('link', {
      name: /Very long sidebar research question 11/i,
    }),
  ).toBeInTheDocument();
  expect(screen.queryByRole('button', {name: 'Show more'})).toBeNull();

  fireEvent.click(screen.getByRole('button', {name: 'Show less'}));

  expect(
    screen.queryByRole('link', {
      name: /Very long sidebar research question 11/i,
    }),
  ).toBeNull();
  expect(screen.getByRole('button', {name: 'Show more'})).toBeInTheDocument();
});
