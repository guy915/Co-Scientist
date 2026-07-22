import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter} from 'react-router-dom';
import {describe, expect, it} from 'vitest';
import {EDGE_KINDS, clusters, edges, nodes} from '../proposals/proposals_data';
import {ProposalsPage} from './proposals_page';

function renderPage(path = '/proposals') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ProposalsPage />
    </MemoryRouter>,
  );
}

describe('ProposalsPage', () => {
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

  describe('node selection and detail', () => {
    it('opens the detail for a node named in the query string', () => {
      renderPage('/proposals?node=brute-force');
      const detail = screen.getByLabelText('Brute-force generation detail');
      expect(
        within(detail).getByText('Brute-force generation'),
      ).toBeInTheDocument();
    });

    it('closes the detail when the open node is chosen again', async () => {
      const {container} = renderPage('/proposals?node=live-session');
      expect(container.querySelector('.proposals-detail')).toBeInTheDocument();
      await userEvent.click(
        screen.getByRole('button', {name: /^Live sessions\./}),
      );
      // The panel stays mounted while it slides back out, so dismissal shows
      // up as the leaving state rather than as an immediate unmount.
      expect(
        container.querySelector('.proposals-detail.is-leaving'),
      ).not.toBeNull();
    });

    it('lights only the relationships the selected node leads with', () => {
      // Live sessions has three outgoing "enables" arrows and one mutual
      // tension authored from the other end; all four lead away from it.
      const {container} = renderPage('/proposals?node=live-session');
      expect(container.querySelectorAll('.proposals-edge.is-lit')).toHaveLength(
        4,
      );
    });

    it('leaves an incoming arrow unlit at its target', () => {
      // Question generation only receives an "enables" arrow, so selecting it
      // lights nothing: the arrow is a statement about Live sessions.
      const {container} = renderPage('/proposals?node=question-generation');
      expect(container.querySelectorAll('.proposals-edge.is-lit')).toHaveLength(
        0,
      );
    });

    it('hides the legends while a detail is open', () => {
      const {container} = renderPage('/proposals?node=live-session');
      expect(container.querySelector('.proposals-legend')).toBeNull();
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
  });

  describe('legend filters', () => {
    it('offers every category and relationship kind as a toggle', () => {
      const {container} = renderPage();
      // Scoped to the legend: category names also appear as the graph's own
      // group labels.
      const categories = within(
        container.querySelector<HTMLElement>(
          '.proposals-legend.is-categories',
        )!,
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
          container.querySelector<HTMLElement>(
            '.proposals-legend.is-categories',
          )!,
        ).getByRole('button', {name: 'Scaling generation'}),
      );
      const dimmed = container.querySelectorAll('.proposals-node.is-dim');
      const outside = nodes.filter(node => node.cluster !== 'scaling');
      expect(dimmed).toHaveLength(outside.length);
    });

    it('stacks categories', async () => {
      const {container} = renderPage();
      const categories = within(
        container.querySelector<HTMLElement>(
          '.proposals-legend.is-categories',
        )!,
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
});
