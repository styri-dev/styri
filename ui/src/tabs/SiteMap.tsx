import { type MouseEvent, useMemo, useRef, useState } from "react";
import type { PanelContext } from "../App";
import type { GraphNode, RobotModel } from "../bridge";
import { ControlDrawer } from "../control/ControlDrawer";
import { levelOf } from "./Fleet";

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
  if (site?.background && size) {
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
  const nodes = site?.graph?.nodes ?? [];
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const robots = ctx.state.fleet;
  const robot = robots.find((r) => r.index === ctx.robot) ?? robots[0];
  const [size, setSize] = useState<[number, number]>();
  const [target, setTarget] = useState<{ x: number; y: number; node?: string } | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const v = bounds(ctx, robots, size);
  const sx = (x: number) => x - v.x0;
  const sy = (y: number) => v.y1 - y;
  const unit = Math.max(v.w, v.h) / 100; // one percent of the map
  const canGo = !!ctx.state.control?.logged_in && !!robot?.capabilities.can_waypoint && !robot.stale;

  const click = (e: MouseEvent<SVGSVGElement>) => {
    if (!canGo || !robot) return;
    const m = svg.current!.getScreenCTM()!.inverse();
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m);
    const x = p.x + v.x0, y = v.y1 - p.y;
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
  return (
    <div className="page mapview">
      {(site?.problems ?? []).map((p) => <p key={p} className="warn-fg small" role="alert">{p}</p>)}
      <div className="mapview__wrap">
        <svg ref={svg} className="sitemap" data-testid="site-map" viewBox={`0 0 ${v.w} ${v.h}`} onClick={click}
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
          {site?.graph?.edges.map((e) => {
            const a = byId.get(e.start), b = byId.get(e.end);
            return a && b && <line key={e.id} className="sitemap__edge" x1={sx(a.x)} y1={sy(a.y)} x2={sx(b.x)} y2={sy(b.y)} strokeWidth={unit * 0.4} />;
          })}
          {nodes.map((n) => (
            <g key={n.id}>
              <circle className="sitemap__node" cx={sx(n.x)} cy={sy(n.y)} r={unit * 0.9} />
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
              onClick={(e) => { e.stopPropagation(); ctx.setRobot(r.index); setTarget(null); }}>
              {r.protocol === "ros2"
                ? <circle r={unit * 2.2} strokeWidth={unit * 0.5} />
                : <rect x={-unit * 2.1} y={-unit * 2.1} width={unit * 4.2} height={unit * 4.2} rx={unit * 0.5} strokeWidth={unit * 0.5} />}
              <line className="marker__heading" x1={0} y1={0} x2={unit * 3.2 * Math.cos(r.pose.theta)} y2={-unit * 3.2 * Math.sin(r.pose.theta)} strokeWidth={unit * 0.6} />
              <text x={0} y={unit * 5} textAnchor="middle" fontSize={unit * 2.4}>{r.name}</text>
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
      {robot && <p className="small text-3">{canGo ? `Tap the map to send ${robot.name} somewhere. Tap a robot to pick it.` : "Tap a robot to pick it."}</p>}
      {robot && <ControlDrawer ctx={ctx} robot={robot} onLogin={onLogin} />}
    </div>
  );
}
