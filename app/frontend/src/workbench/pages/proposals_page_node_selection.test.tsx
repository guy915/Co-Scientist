import {screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {expect, it} from 'vitest';
import {renderPage} from './proposals_page_test_support';

it('opens the detail for a node named in the query string', () => {
  renderPage('/proposals?node=brute-force');
  const detail = screen.getByLabelText('Brute-force generation detail');
  expect(
    within(detail).getByText('Brute-force generation'),
  ).toBeInTheDocument();
});

it('closes the detail when the open node is chosen again', async () => {
  const {container} = renderPage('/proposals?node=lab-integration');
  expect(container.querySelector('.proposals-detail')).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole('link', {name: /^Lab system integration\./}),
  );
  // The panel stays mounted while it slides back out, so dismissal shows
  // up as the leaving state rather than as an immediate unmount.
  expect(
    container.querySelector('.proposals-detail.is-leaving'),
  ).not.toBeNull();
});

it('lights only the relationships the selected node leads with', () => {
  // Lab system integration authors three synergies and one
  // "compensates"; all four lead away from it.
  const {container} = renderPage('/proposals?node=lab-integration');
  expect(container.querySelectorAll('.proposals-edge.is-lit')).toHaveLength(4);
});

it('leaves an incoming arrow unlit at its target', () => {
  // Unreinforced model eval only receives an "enables" arrow, so selecting
  // it lights nothing: the arrow is a statement about Model fusion.
  const {container} = renderPage('/proposals?node=unreinforced-eval');
  expect(container.querySelectorAll('.proposals-edge.is-lit')).toHaveLength(0);
});

it('hides the legends while a detail is open', () => {
  const {container} = renderPage('/proposals?node=lab-integration');
  expect(container.querySelector('.proposals-legend')).toBeNull();
});

it('ignores an unknown node in the query string', () => {
  const {container} = renderPage('/proposals?node=not-a-proposal');
  expect(container.querySelector('.proposals-detail')).toBeNull();
});

it('opens the detail when a node is selected', async () => {
  renderPage();
  await userEvent.click(screen.getByRole('link', {name: /^Adversary agent\./}));
  expect(
    await screen.findByLabelText('Adversary agent detail'),
  ).toBeInTheDocument();
});

it('walks to a related proposal from the detail panel', async () => {
  renderPage('/proposals?node=transitivity');
  const detail = screen.getByLabelText('Transitivity flagging detail');
  await userEvent.click(
    within(detail).getAllByRole('button', {
      name: 'OKF knowledge export',
    })[0],
  );
  expect(
    await screen.findByLabelText('OKF knowledge export detail'),
  ).toBeInTheDocument();
});

it('shows both relationships of a doubled pair', () => {
  renderPage('/proposals?node=transitivity');
  const detail = screen.getByLabelText('Transitivity flagging detail');
  expect(within(detail).getByText(/depends on/)).toBeInTheDocument();
  expect(
    within(detail).getByText(/mitigates a weakness of/),
  ).toBeInTheDocument();
});
