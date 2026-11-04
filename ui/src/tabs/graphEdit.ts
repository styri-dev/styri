// The map editor's changes to a node graph. Pure: each returns a new graph.
import type { GraphNode, Site } from "../bridge";

export type Graph = NonNullable<Site["graph"]>;

function nextId(prefix: string, taken: string[]): string {
  for (let i = 1; ; i++) if (!taken.includes(`${prefix}${i}`)) return `${prefix}${i}`;
}

const round = (v: number) => Math.round(v * 100) / 100; // centimetres

export function addNode(g: Graph, x: number, y: number, mapId: string): Graph {
  const node: GraphNode = { id: nextId("n", g.nodes.map((n) => n.id)), x: round(x), y: round(y), map_id: mapId };
  return { ...g, nodes: [...g.nodes, node] };
}

export function moveNode(g: Graph, id: string, x: number, y: number): Graph {
  return { ...g, nodes: g.nodes.map((n) => (n.id === id ? { ...n, x: round(x), y: round(y) } : n)) };
}

export function removeNode(g: Graph, id: string): Graph {
  return { nodes: g.nodes.filter((n) => n.id !== id), edges: g.edges.filter((e) => e.start !== id && e.end !== id) };
}

export function addEdge(g: Graph, start: string, end: string): Graph {
  const exists = g.edges.some((e) => (e.start === start && e.end === end) || (e.start === end && e.end === start));
  if (start === end || exists) return g;
  return { ...g, edges: [...g.edges, { id: nextId("e", g.edges.map((e) => e.id)), start, end }] };
}

export function removeEdge(g: Graph, id: string): Graph {
  return { ...g, edges: g.edges.filter((e) => e.id !== id) };
}
