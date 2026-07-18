import {describe, expect, it} from 'vitest';
import {
  EDGE_KINDS,
  clusters,
  edges,
  nodes,
  type EdgeKind,
} from './proposals_data';
import {computeLayout} from './proposals_layout';

// The layout is a function of the space it is given, so these assertions
// pin it to one representative stage rather than to a module constant.
const {positions: nodePositions, edges: edgeGeometry} = computeLayout({
  width: 1440,
  height: 760,
});
import {degreeOf, relationsOf} from './proposals_relations';

describe('proposals data', () => {
  it('references only nodes that exist', () => {
    const ids = new Set(nodes.map(node => node.id));
    const dangling = edges
      .flatMap(edge => [edge.from, edge.to])
      .filter(id => !ids.has(id));
    expect(dangling).toEqual([]);
  });

  it('assigns every node to a declared cluster', () => {
    const clusterIds = new Set(clusters.map(cluster => cluster.id));
    const orphans = nodes.filter(node => !clusterIds.has(node.cluster));
    expect(orphans).toEqual([]);
  });

  it('uses only declared edge kinds', () => {
    const kinds = new Set<EdgeKind>(EDGE_KINDS.map(entry => entry.kind));
    const unknown = edges.filter(edge => !kinds.has(edge.kind));
    expect(unknown).toEqual([]);
  });

  it('gives every node a unique id', () => {
    expect(new Set(nodes.map(node => node.id)).size).toBe(nodes.length);
  });

  it('keeps both edges of a doubled pair', () => {
    // persistent-kb/transitivity carries an `enables` and a `compensates`
    // in opposite directions; deduplicating by pair would drop one.
    const between = edges.filter(
      edge =>
        [edge.from, edge.to].includes('persistent-kb') &&
        [edge.from, edge.to].includes('transitivity'),
    );
    expect(between.map(edge => edge.kind).sort()).toEqual([
      'compensates',
      'enables',
    ]);
  });
});

describe('proposals layout', () => {
  it('positions every node', () => {
    const missing = nodes.filter(node => !nodePositions[node.id]);
    expect(missing).toEqual([]);
  });

  it('is deterministic across reads', () => {
    const first = JSON.stringify(nodePositions);
    const second = JSON.stringify(nodePositions);
    expect(first).toBe(second);
  });

  it('keeps clustered nodes nearer their own group than another', () => {
    // The grouping has to be visible spatially, not just by color.
    const scaling = nodes.filter(node => node.cluster === 'scaling');
    const knowledge = nodes.filter(node => node.cluster === 'knowledge');
    const withinScaling = Math.max(
      ...scaling.map(a =>
        Math.min(
          ...scaling
            .filter(b => b.id !== a.id)
            .map(b =>
              Math.hypot(
                nodePositions[a.id].x - nodePositions[b.id].x,
                nodePositions[a.id].y - nodePositions[b.id].y,
              ),
            ),
        ),
      ),
    );
    const acrossGroups = Math.min(
      ...scaling.flatMap(a =>
        knowledge.map(b =>
          Math.hypot(
            nodePositions[a.id].x - nodePositions[b.id].x,
            nodePositions[a.id].y - nodePositions[b.id].y,
          ),
        ),
      ),
    );
    expect(withinScaling).toBeLessThan(acrossGroups);
  });

  it('bows apart the edges of a doubled pair', () => {
    const doubled = edgeGeometry.filter(
      ({edge}) =>
        [edge.from, edge.to].includes('persistent-kb') &&
        [edge.from, edge.to].includes('transitivity'),
    );
    expect(doubled).toHaveLength(2);
    // A quadratic segment means the edge was offset off the straight line.
    for (const geometry of doubled) {
      expect(geometry.path).toContain('Q');
    }
    expect(doubled[0].path).not.toBe(doubled[1].path);
  });

  it('draws a lone edge straight', () => {
    const single = edgeGeometry.find(
      ({edge}) =>
        edge.from === 'live-session' && edge.to === 'question-generation',
    );
    expect(single?.path).toContain('L');
    expect(single?.path).not.toContain('Q');
  });
});

describe('relations', () => {
  it('counts every edge touching a node, including doubled pairs', () => {
    expect(degreeOf('brute-force')).toBe(
      edges.filter(
        edge => edge.from === 'brute-force' || edge.to === 'brute-force',
      ).length,
    );
  });

  it('makes brute-force the most connected proposal', () => {
    // The page's central claim: most of the tension routes through it.
    const degrees = nodes.map(node => degreeOf(node.id));
    expect(degreeOf('brute-force')).toBe(Math.max(...degrees));
  });

  it('reverses directed phrasing for the inbound side', () => {
    // live-session enables question-generation, so the relationship reads
    // one way from each end.
    const outbound = relationsOf('live-session').find(
      relation => relation.other.id === 'question-generation',
    );
    const inbound = relationsOf('question-generation').find(
      relation => relation.other.id === 'live-session',
    );
    expect(outbound?.phrase).toBe('is a prerequisite for');
    expect(inbound?.phrase).toBe('depends on');
  });

  it('reads undirected kinds the same from both ends', () => {
    const forward = relationsOf('brute-force').find(
      relation =>
        relation.other.id === 'live-session' && relation.kind === 'tension',
    );
    const back = relationsOf('live-session').find(
      relation =>
        relation.other.id === 'brute-force' && relation.kind === 'tension',
    );
    expect(forward?.phrase).toBe(back?.phrase);
  });

  it('groups a node relations by kind in legend order', () => {
    const order = EDGE_KINDS.map(entry => entry.kind);
    const kinds = relationsOf('brute-force').map(relation => relation.kind);
    const sorted = [...kinds].sort(
      (a, b) => order.indexOf(a) - order.indexOf(b),
    );
    expect(kinds).toEqual(sorted);
  });
});
