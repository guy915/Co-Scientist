import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter} from 'react-router-dom';
import {describe, expect, it} from 'vitest';
import {edges, nodes} from '../proposals/proposals_data';
import {ProposalsPage} from './proposals_page';

function renderPage(path = '/proposals') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ProposalsPage />
    </MemoryRouter>,
  );
}

describe('ProposalsPage', () => {
  it('renders every proposal in the prose section', () => {
    const {container} = renderPage();
    for (const node of nodes) {
      // Anchored by id so the graph and a deep link address the same thing.
      expect(container.querySelector(`#proposal-${node.id}`)).not.toBeNull();
    }
  });

  it('draws a node and an edge for every entry in the data', () => {
    const {container} = renderPage();
    expect(container.querySelectorAll('.proposals-node')).toHaveLength(
      nodes.length,
    );
    expect(
      container.querySelectorAll('.proposals-graph .proposals-edge'),
    ).toHaveLength(edges.length);
  });

  it('opens the detail for a node named in the query string', () => {
    renderPage('/proposals?node=brute-force');
    const detail = screen.getByLabelText('Brute-force generation detail');
    expect(
      within(detail).getByText('Brute-force generation'),
    ).toBeInTheDocument();
  });

  it('ignores an unknown node in the query string', () => {
    const {container} = renderPage('/proposals?node=not-a-proposal');
    expect(container.querySelector('.proposals-detail')).toBeNull();
  });

  it('opens the detail when a node is selected', async () => {
    renderPage();
    await userEvent.click(
      screen.getByRole('button', {name: /^Adversary agent\./}),
    );
    expect(
      await screen.findByLabelText('Adversary agent detail'),
    ).toBeInTheDocument();
  });

  it('walks to a related proposal from the detail panel', async () => {
    renderPage('/proposals?node=transitivity');
    const detail = screen.getByLabelText('Transitivity flagging detail');
    await userEvent.click(
      within(detail).getAllByRole('button', {
        name: 'Persistent knowledge base',
      })[0],
    );
    expect(
      await screen.findByLabelText('Persistent knowledge base detail'),
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

  it('filters the graph down to a single relationship kind', async () => {
    const {container} = renderPage();
    await userEvent.click(screen.getByRole('button', {name: /Tension —/}));
    const drawn = container.querySelectorAll(
      '.proposals-graph .proposals-edge',
    );
    const tensions = edges.filter(edge => edge.kind === 'tension');
    expect(drawn).toHaveLength(tensions.length);
  });

  it('restores every kind from the reset control', async () => {
    const {container} = renderPage();
    await userEvent.click(screen.getByRole('button', {name: /Tension —/}));
    await userEvent.click(
      screen.getByRole('button', {name: 'Show all relationships'}),
    );
    expect(
      container.querySelectorAll('.proposals-graph .proposals-edge'),
    ).toHaveLength(edges.length);
  });

  it('gives every node a keyboard-reachable control', () => {
    const {container} = renderPage();
    const focusable = container.querySelectorAll(
      '.proposals-node[tabindex="0"]',
    );
    expect(focusable).toHaveLength(nodes.length);
  });

  it('selects a node from the keyboard', async () => {
    renderPage();
    const node = screen.getByRole('button', {name: /^Live sessions\./});
    node.focus();
    await userEvent.keyboard('{Enter}');
    expect(
      await screen.findByLabelText('Live sessions detail'),
    ).toBeInTheDocument();
  });
});
