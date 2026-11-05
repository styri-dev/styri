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

/** Connect two nodes. Connecting them again makes the edge one-way, from `start`; once more, two-way. */
export function addEdge(g: Graph, start: string, end: string): Graph {
  if (start === end) return g;
  const same = g.edges.find((e) => (e.start === start && e.end === end) || (e.start === end && e.end === start));
  if (same) {
    const edge = same.directed ? { id: same.id, start: same.start, end: same.end } : { ...same, start, end, directed: true };
    return { ...g, edges: g.edges.map((e) => (e === same ? edge : e)) };
  }
  return { ...g, edges: [...g.edges, { id: nextId("e", g.edges.map((e) => e.id)), start, end }] };
}

/** The shortest path along the graph, honouring one-way edges: node ids, or null. */
export function findRoute(g: Graph, start: string, goal: string): string[] | null {
  const at = new Map(g.nodes.map((n) => [n.id, n]));
  const best = new Map([[start, 0]]);
  const came = new Map<string, string>();
  const open = new Set([start]);
  while (open.size) {
    const here = [...open].reduce((a, b) => (best.get(a)! <= best.get(b)! ? a : b));
    open.delete(here);
    if (here === goal) break;
    for (const e of g.edges) {
      const there = e.start === here ? e.end : e.end === here && !e.directed ? e.start : null;
      const a = at.get(here), b = there ? at.get(there) : undefined;
      if (!a || !b) continue;
      const d = best.get(here)! + Math.hypot(a.x - b.x, a.y - b.y);
      if (d < (best.get(b.id) ?? Infinity)) { best.set(b.id, d); came.set(b.id, here); open.add(b.id); }
    }
  }
  if (!best.has(goal)) return null;
  const path = [goal];
  while (path[0] !== start) path.unshift(came.get(path[0])!);
  return path;
}

export function removeEdge(g: Graph, id: string): Graph {
  return { ...g, edges: g.edges.filter((e) => e.id !== id) };
}
