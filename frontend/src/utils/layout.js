/**
 * 自动布局算法 — 用dagre把流程图从上到下排列
 */

import Dagre from '@dagrejs/dagre';

export function layoutGraph(nodes, edges, direction = 'TB') {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

  g.setGraph({
    rankdir: direction,
    nodesep: 120,        // 同层间距加大，防止重叠
    ranksep: 100,        // 层间距
    edgesep: 40,         // 边与边间距
    marginx: 50,
    marginy: 50,
  });

  nodes.forEach(node => {
    g.setNode(node.id, { width: 160, height: 56 });
  });

  edges.forEach(edge => {
    g.setEdge(edge.source, edge.target);
  });

  Dagre.layout(g);

  return nodes.map(node => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: { x: pos.x - 80, y: pos.y - 28 },
    };
  });
}
