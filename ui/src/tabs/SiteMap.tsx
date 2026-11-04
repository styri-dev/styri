import { type MouseEvent, type PointerEvent, useEffect, useMemo, useRef, useState } from "react";
import type { PanelContext } from "../App";
import type { GraphNode, RobotModel } from "../bridge";
import { ControlDrawer } from "../control/ControlDrawer";
import { levelOf } from "./Fleet";
import { addEdge, addNode, type Graph, moveNode, removeEdge, removeNode } from "./graphEdit";

type Tool = "move" | "add" | "connect" | "delete";
const TOOLS: [Tool, string, string][] = [
  ["move", "Move", "Drag a node."],
  ["add", "Add node", "Tap the map to add a node."],
  ["connect", "Connect", "Tap two nodes to join them, or tap one and then another to chain."],
  ["delete", "Delete", "Tap a node or an edge to delete it."],
];

const MARGIN = 1.5; // metres around what's drawn

interface View {
  x0: number;
  y1: number; // top edge: y runs up on the map and down on screen
  w: number;
  h: number;
}

function bounds(ctx: PanelContext, robots: RobotModel[], size?: [number, number]): View {
  const site = ctx.state.hello?.site;
  const pts: [number, number][] = [...(site?.graph?.nodes ?? []).map((n): [number, number] => [n.x, n.y])];
  robots.forEach((r) => r.pose && pts.push([r.pose.x, r.pose.y]));
  // A background is often bigger than the site: fit what's on it, unless it's all there is.
  if (!pts.length && site?.background && size) {
    const [ox, oy] = site.background.origin;
    pts.push([ox, oy], [ox + size[0] * site.background.scale, oy + size[1] * site.background.scale]);
  }
  if (!pts.length) pts.push([0, 0], [10, 6]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs) - MARGIN, y0 = Math.min(...ys) - MARGIN;
  const x1 = Math.max(...xs) + MARGIN, y1 = Math.max(...ys) + MARGIN;
  return { x0, y1, w: Math.max(x1 - x0, 4), h: Math.max(y1 - y0, 4) };
}

function nearest(nodes: GraphNode[], x: number, y: number): GraphNode | undefined {
  return nodes.reduce<GraphNode | undefined>((best, n) =>
    !best || Math.hypot(n.x - x, n.y - y) < Math.hypot(best.x - x, best.y - y) ? n : best, undefined);
}

export function SiteMap({ ctx, onLogin }: { ctx: PanelContext; onLogin: () => void }) {
  const site = ctx.state.hello?.site;
  const [draft, setDraft] = useState<Graph | null>(null); // the graph being edited, until it's saved
  const [tool, setTool] = useState<Tool>("move");
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const dragging = useRef<string | null>(null);
  const frozen = useRef<View | null>(null); // the view holds still while nodes move
  const nodes = draft?.nodes ?? site?.graph?.nodes ?? [];
  const edges = draft?.edges ?? site?.graph?.edges ?? [];
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const robots = ctx.state.fleet;
  const robot = robots.find((r) => r.index === ctx.robot) ?? robots[0];
  const [size, setSize] = useState<[number, number]>();
  const [target, setTarget] = useState<{ x: number; y: number; node?: string } | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const v = frozen.current ?? bounds(ctx, robots, size);
  const sx = (x: number) => x - v.x0;
  const sy = (y: number) => v.y1 - y;
  const unit = Math.max(v.w, v.h) / 100; // one percent of the map
  const loggedIn = !!ctx.state.control?.logged_in;
  const canGo = !draft && loggedIn && !!robot?.capabilities.can_waypoint && !robot.stale;

  const world = (e: { clientX: number; clientY: number }) => {
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.current!.getScreenCTM()!.inverse());
    return { x: p.x + v.x0, y: v.y1 - p.y };
  };

  // A new node goes on the map the robots report, so VDA 5050 orders match it.
  const mapId = () => nodes[0]?.map_id ?? robots.find((r) => r.protocol === "vda5050" && r.pose)?.pose?.map_id ?? "site";

  const startEdit = () => {
    frozen.current = v;
    setDraft({ nodes, edges });
    setTool("move");
    setTarget(null);
  };
  const stopEdit = () => {
    frozen.current = null;
    setDraft(null);
    setLinkFrom(null);
    setSaving(false);
  };
  const save = () => {
    setSaving(true);
    ctx.send({ action: "GRAPH_SAVE", graph: draft });
  };
  // Saved: the bridge sends the new site to everyone. Refused: a notice, and the draft stays.
  const saved = ctx.state.hello?.site;
  useEffect(() => { if (saving) stopEdit(); }, [saved]); // eslint-disable-line react-hooks/exhaustive-deps
  const refused = ctx.state.notice?.at;
  useEffect(() => { setSaving(false); }, [refused]);

  const tapNode = (e: PointerEvent, id: string) => {
    if (!draft) return;
    e.stopPropagation();
    if (tool === "delete") {
      setDraft(removeNode(draft, id));
    } else if (tool === "connect") {
      if (linkFrom) setDraft(addEdge(draft, linkFrom, id));
      setLinkFrom(id);
    } else if (tool === "move") {
      dragging.current = id;
      svg.current!.setPointerCapture(e.pointerId);
    }
  };
  const drag = (e: PointerEvent) => {
    if (draft && dragging.current) {
      const { x, y } = world(e);
      setDraft(moveNode(draft, dragging.current, x, y));
    }
  };

  const click = (e: MouseEvent<SVGSVGElement>) => {
    if (draft) {
      if (tool === "add") {
        const { x, y } = world(e);
        setDraft(addNode(draft, x, y, mapId()));
      }
      return;
    }
    if (!canGo || !robot) return;
    const { x, y } = world(e);
    if (robot.protocol === "vda5050") {
      const n = nearest(nodes, x, y);
      if (n) setTarget({ x: n.x, y: n.y, node: n.id });
    } else {
      setTarget({ x, y });
    }
  };

  const go = () => {
    if (!robot || !target) return;
    ctx.send(target.node ? { action: "GOAL", robot: robot.id, node: target.node }
      : { action: "GOAL", robot: robot.id, x: target.x, y: target.y, theta: 0 });
    setTarget(null);
  };

  const bg = site?.background;
  const refusal = draft && ctx.state.notice && !ctx.state.notice.robot ? ctx.state.notice.text : null;
  return (
    <div className="page mapview">
      {(site?.problems ?? []).map((p) => <p key={p} className="warn-fg small" role="alert">{p}</p>)}
      {loggedIn && site?.editable && !draft && (
        <div className="mapedit"><button type="button" className="btn btn--plain" data-testid="edit-graph" onClick={startEdit}>Edit graph</button></div>
      )}
      {draft && (
        <div className="mapedit" role="toolbar" aria-label="Edit the node graph">
          {TOOLS.map(([key, label]) => (
            <button key={key} type="button" className={`btn btn--plain ${tool === key ? "is-on" : ""}`} aria-pressed={tool === key}
              data-testid={`tool-${key}`} onClick={() => { setTool(key); setLinkFrom(null); }}>{label}</button>
          ))}
          <span className="spacer" />
          <button type="button" className="btn btn--plain" onClick={stopEdit}>Discard</button>
          <button type="button" className="btn btn--solid" data-testid="save-graph" disabled={saving} onClick={save}>Save graph</button>
        </div>
      )}
      {draft && <p className="small text-3" data-testid="graph-count">{TOOLS.find(([k]) => k === tool)![2]} {draft.nodes.length} nodes, {draft.edges.length} edges. Orders already running keep their route.</p>}
      {refusal && <p className="warn-fg small" role="alert" data-testid="graph-error">{refusal}</p>}
      <div className="mapview__wrap">
        <svg ref={svg} className={`sitemap ${draft ? "is-editing" : ""}`} data-testid="site-map" viewBox={`0 0 ${v.w} ${v.h}`}
          onClick={click} onPointerMove={drag} onPointerUp={() => { dragging.current = null; }}
          role="img" aria-label="Site map with robots">
          {bg && (
            <image href={bg.url} x={sx(bg.origin[0])} y={sy(bg.origin[1] + (size?.[1] ?? 0) * bg.scale)}
              width={(size?.[0] ?? 0) * bg.scale} height={(size?.[1] ?? 0) * bg.scale}
              onLoad={(e) => {
                const probe = new Image();
                probe.onload = () => setSize([probe.width, probe.height]);
                probe.src = (e.target as SVGImageElement).href.baseVal;
              }} />
          )}
          {edges.map((e) => {
            const a = byId.get(e.start), b = byId.get(e.end);
            return a && b && (
              <g key={e.id} data-edge={e.id}>
                <line className="sitemap__edge" x1={sx(a.x)} y1={sy(a.y)} x2={sx(b.x)} y2={sy(b.y)} strokeWidth={unit * 0.4} />
                {draft && tool === "delete" && (
                  <line className="sitemap__hit" x1={sx(a.x)} y1={sy(a.y)} x2={sx(b.x)} y2={sy(b.y)} strokeWidth={unit * 4}
                    onPointerDown={(ev) => { ev.stopPropagation(); setDraft(removeEdge(draft, e.id)); }} />
                )}
              </g>
            );
          })}
          {nodes.map((n) => (
            <g key={n.id} data-node={n.id}>
              <circle className={`sitemap__node ${linkFrom === n.id ? "is-from" : ""}`} cx={sx(n.x)} cy={sy(n.y)} r={unit * (draft ? 1.6 : 0.9)} />
              {/* A finger needs more than the dot. */}
              {draft && <circle className="sitemap__hit" cx={sx(n.x)} cy={sy(n.y)} r={unit * 3.5} onPointerDown={(ev) => tapNode(ev, n.id)} onClick={(ev) => ev.stopPropagation()} />}
              <text className="sitemap__label" x={sx(n.x) + unit * 1.3} y={sy(n.y) - unit * 1.3} fontSize={unit * 2}>{n.id}</text>
            </g>
          ))}
          {robots.map((r) => {
            const route = r.task.route.map((id) => byId.get(id)).filter((n): n is GraphNode => !!n);
            return r.pose && route.length > 0 && (
              <polyline key={`route-${r.id}`} className="sitemap__route" strokeWidth={unit * 0.7}
                points={[`${sx(r.pose.x)},${sy(r.pose.y)}`, ...route.map((n) => `${sx(n.x)},${sy(n.y)}`)].join(" ")} />
            );
          })}
          {target && <circle className="sitemap__target" cx={sx(target.x)} cy={sy(target.y)} r={unit * 1.6} strokeWidth={unit * 0.5} />}
          {robots.map((r) => r.pose && (
            <g key={r.id} className={`marker marker--${r.stale ? "unknown" : levelOf(r)} ${r.index === robot?.index ? "is-picked" : ""}`}
              data-robot={r.name} transform={`translate(${sx(r.pose.x)} ${sy(r.pose.y)})`}
              onClick={(e) => { if (draft) return; e.stopPropagation(); ctx.setRobot(r.index); setTarget(null); }}>
              {r.protocol === "ros2"
                ? <circle r={unit * 2.2} strokeWidth={unit * 0.5} />
                : <rect x={-unit * 2.1} y={-unit * 2.1} width={unit * 4.2} height={unit * 4.2} rx={unit * 0.5} strokeWidth={unit * 0.5} />}
              <line className="marker__heading" x1={0} y1={0} x2={unit * 3.2 * Math.cos(r.pose.theta)} y2={-unit * 3.2 * Math.sin(r.pose.theta)} strokeWidth={unit * 0.6} />
              <text x={0} y={unit * 5.6} textAnchor="middle" fontSize={unit * 3}>{r.name}</text>
            </g>
          ))}
        </svg>
        {target && robot && (
          <div className="mapview__go">
            <span>Send <strong>{robot.name}</strong> to {target.node ?? `${target.x.toFixed(1)}, ${target.y.toFixed(1)}`}?</span>
            <button type="button" className="btn btn--solid" data-testid="send-goal" onClick={go}>Send</button>
            <button type="button" className="btn btn--plain" onClick={() => setTarget(null)}>Cancel</button>
          </div>
        )}
      </div>
      {robot && !draft && <p className="small text-3">{canGo ? `Tap the map to send ${robot.name} somewhere. Tap a robot to pick it.` : "Tap a robot to pick it."}</p>}
      {robot && !draft && <ControlDrawer ctx={ctx} robot={robot} onLogin={onLogin} />}
    </div>
  );
}
