import {screen} from '@testing-library/react';
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
        screen.getByRole('link', {name: new RegExp(`^${node.label}\\.`)}),
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
    // Each node is an anchor, so it is in the tab order (and openable in a
    // new browser tab) without a tabindex of its own.
    const focusable = container.querySelectorAll('a.proposals-node[href]');
    expect(focusable).toHaveLength(nodes.length);
  });

  it('focuses a node as a link to its own URL', () => {
    // Activating a focused link on Enter is the browser's own behavior (and
    // user-event declines to emulate it for an SVG anchor), so what is left
    // to pin here is that the focusable control is a real link to the
    // proposal — the URL whose detail panel the test above renders.
    renderPage();
    const node = screen.getByRole('link', {name: /^Lab system integration\./});
    node.focus();
    expect(document.activeElement).toBe(node);
    expect(node).toHaveAttribute('href', '/proposals?node=lab-integration');
  });
});
