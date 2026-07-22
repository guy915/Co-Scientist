import {screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {expect, it} from 'vitest';
import {EDGE_KINDS, clusters, edges, nodes} from '../proposals/proposals_data';
import {renderPage} from './proposals_page_test_support';

it('offers every category and relationship kind as a toggle', () => {
  const {container} = renderPage();
  // Scoped to the legend: category names also appear as the graph's own
  // group labels.
  const categories = within(
    container.querySelector<HTMLElement>('.proposals-legend.is-categories')!,
  );
  for (const cluster of clusters) {
    expect(
      categories.getByRole('button', {name: cluster.label}),
    ).toHaveAttribute('aria-pressed', 'false');
  }
  for (const {label} of EDGE_KINDS) {
    expect(screen.getByRole('button', {name: label})).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  }
});

it('shows every edge while nothing is selected', () => {
  const {container} = renderPage();
  expect(
    container.querySelectorAll('.proposals-edges .proposals-edge'),
  ).toHaveLength(edges.length);
});

it('narrows the graph to one selected relationship kind', async () => {
  const {container} = renderPage();
  await userEvent.click(screen.getByRole('button', {name: 'Tension'}));
  const tensions = edges.filter(edge => edge.kind === 'tension');
  expect(
    container.querySelectorAll('.proposals-edges .proposals-edge'),
  ).toHaveLength(tensions.length);
});

it('stacks relationship kinds', async () => {
  const {container} = renderPage();
  await userEvent.click(screen.getByRole('button', {name: 'Tension'}));
  await userEvent.click(screen.getByRole('button', {name: 'Synergy'}));
  const both = edges.filter(
    edge => edge.kind === 'tension' || edge.kind === 'synergy',
  );
  expect(
    container.querySelectorAll('.proposals-edges .proposals-edge'),
  ).toHaveLength(both.length);
  expect(screen.getByRole('button', {name: 'Tension'})).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});

it('restores every edge when the last selection is cleared', async () => {
  const {container} = renderPage();
  const tension = screen.getByRole('button', {name: 'Tension'});
  await userEvent.click(tension);
  // Unselecting the only chip is what replaces a reset control.
  await userEvent.click(tension);
  expect(tension).toHaveAttribute('aria-pressed', 'false');
  expect(
    container.querySelectorAll('.proposals-edges .proposals-edge'),
  ).toHaveLength(edges.length);
});

it('dims the categories that are not selected', async () => {
  const {container} = renderPage();
  await userEvent.click(
    within(
      container.querySelector<HTMLElement>('.proposals-legend.is-categories')!,
    ).getByRole('button', {name: 'Scaling generation'}),
  );
  const dimmed = container.querySelectorAll('.proposals-node.is-dim');
  const outside = nodes.filter(node => node.cluster !== 'scaling');
  expect(dimmed).toHaveLength(outside.length);
});

it('stacks categories', async () => {
  const {container} = renderPage();
  const categories = within(
    container.querySelector<HTMLElement>('.proposals-legend.is-categories')!,
  );
  await userEvent.click(
    categories.getByRole('button', {name: 'Scaling generation'}),
  );
  await userEvent.click(
    categories.getByRole('button', {name: 'Evaluation rigor'}),
  );
  const outside = nodes.filter(
    node => node.cluster !== 'scaling' && node.cluster !== 'evaluation',
  );
  expect(container.querySelectorAll('.proposals-node.is-dim')).toHaveLength(
    outside.length,
  );
});
