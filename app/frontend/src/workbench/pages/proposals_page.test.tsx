import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it} from 'vitest';
import {edges, nodes} from '../proposals/proposals_data';
import {renderPage} from './proposals_page_test_support';

describe('graph rendering', () => {
  it('names every proposal for assistive technology', () => {
    renderPage();
    // The graph is the only rendering of the content, so each node has to
    // carry its own accessible name.
    for (const node of nodes) {
      expect(
        screen.getByRole('button', {name: new RegExp(`^${node.label}\\.`)}),
      ).toBeInTheDocument();
    }
  });

  it('draws a node and an edge for every entry in the data', () => {
    const {container} = renderPage();
    expect(container.querySelectorAll('.proposals-node')).toHaveLength(
      nodes.length,
    );
    expect(
      container.querySelectorAll('.proposals-edges .proposals-edge'),
    ).toHaveLength(edges.length);
  });
});

describe('keyboard access', () => {
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
