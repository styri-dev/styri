import { type CSSProperties, type PointerEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { PanelContext, SendPlan } from "../App";
import type { GraphNode, RobotModel } from "../bridge";
import { nodeName, PROTOCOL, type RobotView, type VerdictKey } from "../view";
import { addEdge, addNode, findRoute, type Graph, moveNode, removeEdge, removeNode } from "./graphEdit";

type Tool = "move" | "add" | "connect" | "delete";
const TOOLS: [Tool, string, string][] = [
  ["move", "Move", "Drag a node to move it. Tap targets are larger than the dots."],
  ["add", "Add node", "Tap the map to add a node."],
  ["connect", "Connect", "Tap two nodes to connect them. Tap again to make the edge one-way."],
  ["delete", "Delete", "Tap a node or edge to delete it."],
];

const MARGIN = 1.5; // metres around what's drawn
const PHONE_MIN_SCALE = 10; // pixels per metre
const GRAPH_CHANGED = "The graph changed since you opened it. Reload.";

const FILL: Record<VerdictKey, string> = { ok: "var(--ok-500)", warn: "var(--caution-500)", fault: "var(--stop-500)", stale: "var(--bg)", offline: "var(--g-600)" };

interface Bounds { x0: number; y0: number; x1: number; y1: number }
interface Box { x: number; y: number; w: number; h: number }
interface Label extends Box { text: string; color: string; bg: string; border: string; weight: number; pad: number; opacity: number; z: number }

function nearest(nodes: GraphNode[], x: number, y: number): GraphNode | undefined {
  return nodes.reduce<GraphNode | undefined>((best, n) =>
    !best || Math.hypot(n.x - x, n.y - y) < Math.hypot(best.x - x, best.y - y) ? n : best, undefined);
}

/** What the map must show, in site metres. The real map's own size when there is one. */
function boundsOf(nodes: GraphNode[], robots: RobotModel[], bg: { scale: number; origin: [number, number] } | null | undefined, size?: [number, number]): Bounds {
  if (bg && size) {
    const [ox, oy] = bg.origin;
    return { x0: ox, y0: oy, x1: ox + size[0] * bg.scale, y1: oy + size[1] * bg.scale };
  }
  const pts: [number, number][] = nodes.map((n) => [n.x, n.y]);
  robots.forEach((r) => r.pose && pts.push([r.pose.x, r.pose.y]));
  if (!pts.length) pts.push([0, 0], [10, 6]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const b = { x0: Math.min(...xs) - MARGIN, y0: Math.min(...ys) - MARGIN, x1: Math.max(...xs) + MARGIN, y1: Math.max(...ys) + MARGIN };
  if (b.x1 - b.x0 < 4) b.x1 = b.x0 + 4;
  if (b.y1 - b.y0 < 4) b.y1 = b.y0 + 4;
  return b;
}

/** The marker: shape is the protocol, colour the verdict, a separate arrow the heading. */
export function Marker({ protocol, kind, selected, unconfirmed, outline, size = 56, heading = 0 }: {
  protocol: "ros2" | "vda5050"; kind: VerdictKey; selected?: boolean; unconfirmed?: boolean; outline?: boolean; size?: number; heading?: number;
}) {
  const ros = protocol === "ros2", ghost = kind === "stale", off = kind === "offline";
  const vfill = FILL[kind];
  const fill = outline || ghost ? "var(--bg)" : unconfirmed ? "var(--stop-500)" : vfill;
  const stroke = ghost ? "var(--g-500)" : outline ? vfill : "var(--bg)";
  const sw = ghost ? 2 : outline ? 3 : 2;
  const dash = ghost ? "3 3" : undefined;
  const ring = selected ? "var(--accent)" : unconfirmed ? "var(--stop-500)" : null;
  const arrow = ghost || off ? "var(--g-500)" : vfill;
  return (
    <svg className="marker__svg" width={size} height={size} viewBox="-28 -28 56 56">
      <g transform={`rotate(${heading})`}>
        {ring && (ros ? <circle r={21} fill="none" stroke={ring} strokeWidth={3} /> : <rect x={-21} y={-16} width={42} height={32} rx={9} fill="none" stroke={ring} strokeWidth={3} />)}
        <path d={ros ? "M17,-6 L26,0 L17,6 Z" : "M20,-6 L29,0 L20,6 Z"} fill={arrow} />
        {ros ? <circle r={13} fill={fill} stroke={stroke} strokeWidth={sw} strokeDasharray={dash} />
          : <rect x={-16} y={-11} width={32} height={22} rx={5} fill={fill} stroke={stroke} strokeWidth={sw} strokeDasharray={dash} />}
      </g>
    </svg>
  );
}

const KEY: { protocol: "ros2" | "vda5050"; kind: VerdictKey; label: string; inner?: string; outline?: boolean }[] = [
  { protocol: "ros2", kind: "ok", label: "ROS 2" }, { protocol: "vda5050", kind: "ok", label: "VDA 5050" },
  { protocol: "vda5050", kind: "ok", label: "Paused", inner: "❚❚" }, { protocol: "ros2", kind: "stale", label: "Stale" },
  { protocol: "vda5050", kind: "offline", label: "Offline", inner: "⊘" }, { protocol: "vda5050", kind: "warn", label: "Off graph", outline: true },
  { protocol: "ros2", kind: "warn", label: "Warning" }, { protocol: "vda5050", kind: "fault", label: "Fault" },
];

function NoMap({ ctx }: { ctx: PanelContext }) {
  return (
    <div className="nomap" data-testid="no-map">
      <div className="nomap__box">
        <span className="nomap__title">No site map yet</span>
        <span className="nomap__lead">Robots are listed without positions until a map is added. Use a floor-plan image with its scale, or the ROS 2 <span className="mono">/map</span> occupancy grid.</span>
        <span className="small text-3">{ctx.access.admin ? <>Set <span className="mono">site.map</span> or <span className="mono">site.graph</span> in styri.yaml.</> : "Ask your Styri admin to add one."}</span>
      </div>
      <div className="nomap__list">
        {ctx.robots.map((v) => (
          <button key={v.r.name} type="button" className="nomap__row" data-robot={v.r.name} onClick={() => ctx.openRobot(v.r.name)}>
            <span className={`mono nomap__glyph v-${v.key}`}>{v.glyph}</span>
            <span className="flist__two">
              <span><span className="mono strong">{v.r.name}</span> <span className="xsmall text-3">{[PROTOCOL[v.r.protocol], v.r.vendor].filter(Boolean).join(" · ")}</span></span>
              <span className={`small ${v.sideTone === "text-2" ? "text-2" : `v-${v.sideTone}`}`}>{v.side}</span>
            </span>
            <span className="mono">{v.battery} %</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function FleetList({ ctx }: { ctx: PanelContext }) {
  const n = ctx.robots.length;
  return (
    <div className="mapside" data-testid="map-fleet">
      <span className="microlabel mapside__title">FLEET · {n} ROBOT{n === 1 ? "" : "S"}</span>
      {ctx.robots.map((v) => (
        <button key={v.r.name} type="button" className={`mapside__row ${ctx.ui.sel === v.r.name ? "is-on" : ""}`} data-pick={v.r.name} onClick={() => ctx.ui.select(v.r.name)}>
          <span className={`mono mapside__glyph v-${v.key}`}>{v.glyph}</span>
          <span className={`flist__two ${v.dim ? "is-dim" : ""}`}>
            <span className="flist__idline"><span className="mono flist__id">{v.r.name}</span>{v.paused && <span className="flist__paused">❚❚ Paused</span>}</span>
            <span className={`flist__side ellipsis ${v.sideTone === "text-2" ? "text-2" : `v-${v.sideTone}`}`}>{v.side}</span>
          </span>
          <span className={`mono flist__bat ${v.dim ? "is-dim" : ""} ${v.batteryLow ? "tone-warn" : ""}`}>{v.battery} %</span>
        </button>
      ))}
    </div>
  );
}

export function SiteMap({ ctx }: { ctx: PanelContext }) {
  if (!ctx.hasMap) return <NoMap ctx={ctx} />;
  return (
    <div className="mapview">
      {ctx.wide && <FleetList ctx={ctx} />}
      <MapPane ctx={ctx} />
    </div>
  );
}

function MapPane({ ctx }: { ctx: PanelContext }) {
  const { state, ui, access, phone, robots } = ctx;
  const site = state.hello?.site;
  const [draft, setDraft] = useState<Graph | null>(null); // the graph being edited, until it's saved
  const [tool, setTool] = useState<Tool>("move");
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<[number, number]>([0, 0]);
  const [fitAll, setFitAll] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);
  const [size, setSize] = useState<[number, number]>(); // the background's pixels
  const [pane, setPane] = useState<[number, number]>([700, 500]);
  const paneRef = useRef<HTMLDivElement>(null);
  const dragging = useRef<string | null>(null);
  const press = useRef<{ x: number; y: number; px: number; py: number; moved: boolean } | null>(null);
  const openedAt = useRef<string | null>(null); // the version this draft started from
  const frozen = useRef<Bounds | null>(null); // the view holds still while nodes move
  const nodes = useMemo(() => draft?.nodes ?? site?.graph?.nodes ?? [], [draft, site]);
  const edges = draft?.edges ?? site?.graph?.edges ?? [];
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const models = robots.map((v) => v.r);
  const bg = site?.background;

  useLayoutEffect(() => {
    const el = paneRef.current!;
    const measure = () => setPane([el.clientWidth, el.clientHeight]);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    if (!bg) return;
    const probe = new Image();
    probe.onload = () => setSize([probe.width, probe.height]);
    probe.src = bg.url;
  }, [bg]);

  const editing = !!draft;
  const selV = robots.find((v) => v.r.name === ui.sel);
  const sel = selV?.r;
  const drive = ui.drive && !!sel;
  const [mw, mh] = pane;
  const sheetOn = phone && !!sel;
  const visH = drive && phone ? mh * 0.22 : sheetOn ? Math.max(160, mh - (ui.sheetH || 250)) : mh;
  const sheetOpen = sheetOn && ui.sheetOpen && !drive;

  // The fit: cover and centre on the selection, or the whole floor. Same rules as the design's.
  const B = frozen.current ?? boundsOf(nodes, models, bg, size);
  const bw = B.x1 - B.x0, bh = B.y1 - B.y0;
  const fit = Math.max(1, phone || fitAll ? Math.min((mw - 32) / bw, (visH - 24) / bh) : Math.max((mw - 16) / bw, (visH - 16) / bh));
  const sc = (phone ? Math.max(fit, PHONE_MIN_SCALE) : fit) * zoom;
  const focusP = sel?.pose ?? { x: (B.x0 + B.x1) / 2, y: (B.y0 + B.y1) / 2 };
  let ox = (mw - bw * sc) / 2 - B.x0 * sc;
  let oy = (visH - bh * sc) / 2 + B.y1 * sc;
  if (bw * sc > mw - 16) ox = Math.min(16 - B.x0 * sc, Math.max(mw - 16 - B.x1 * sc, mw / 2 - focusP.x * sc));
  if (bh * sc > visH - 16) oy = Math.max(visH - 16 + B.y0 * sc, Math.min(16 + B.y1 * sc, visH / 2 + focusP.y * sc));
  if (drive || sheetOpen) { ox = mw / 2 - focusP.x * sc; oy = visH / 2 + focusP.y * sc; }
  ox += pan[0];
  oy += pan[1];
  const X = (x: number) => ox + x * sc;
  const Y = (y: number) => oy - y * sc;
  const toWorld = (px: number, py: number) => ({ x: (px - ox) / sc, y: (oy - py) / sc });
  const focus = !!sel && !editing;

  // ---- Send to… -----------------------------------------------------------
  const planFor = (r: RobotModel, p: { x: number; y: number }): SendPlan => {
    const from = r.pose ?? p;
    if (r.protocol === "ros2") {
      const len = Math.hypot(p.x - from.x, p.y - from.y);
      return { step: "confirm", dest: `point ${p.x.toFixed(1)}, ${p.y.toFixed(1)} m`, point: [p.x, p.y], path: [[from.x, from.y], [p.x, p.y]], via: `Straight path · ${len.toFixed(0)} m · planner may adjust` };
    }
    const goal = nearest(nodes, p.x, p.y);
    const start = nearest(nodes, from.x, from.y);
    if (!goal || !start) return { step: "pick" };
    const ids = findRoute({ nodes, edges }, start.id, goal.id);
    const dest = nodeName(site, goal.id);
    if (!ids) return { step: "confirm", node: goal.id, dest, path: [[from.x, from.y], [goal.x, goal.y]], via: "No route on the graph — check one-way edges" };
    const pts: [number, number][] = [[from.x, from.y], ...ids.map((id): [number, number] => [byId.get(id)!.x, byId.get(id)!.y])];
    const len = pts.slice(1).reduce((sum, q, i) => sum + Math.hypot(q[0] - pts[i][0], q[1] - pts[i][1]), 0);
    return { step: "confirm", node: goal.id, dest, path: pts, via: `${ids.map((id) => nodeName(site, id)).join(" → ")} · ${ids.length} nodes · ${len.toFixed(0)} m` };
  };
  const doSend = () => {
    const plan = ui.send;
    if (!sel || !plan) return;
    ctx.send(plan.node ? { action: "GOAL", robot: sel.id, node: plan.node }
      : { action: "GOAL", robot: sel.id, x: plan.point![0], y: plan.point![1], theta: 0 });
    ui.setSend(null);
  };

  // ---- the graph editor ---------------------------------------------------
  const startEdit = () => {
    frozen.current = B;
    openedAt.current = site?.version ?? null;
    setDraft({ nodes, edges });
    setTool("move");
    ui.setSend(null);
    setKeyOpen(false);
    setSavedAt(0);
  };
  const stopEdit = () => {
    frozen.current = null;
    setDraft(null);
    setLinkFrom(null);
    setSaving(false);
  };
  const save = () => {
    setSaving(true);
    ctx.send({ action: "GRAPH_SAVE", graph: draft, version: openedAt.current });
  };
  // Saved: the bridge sends the new site to everyone. Refused: a notice, and the draft stays.
  useEffect(() => {
    if (saving) { stopEdit(); setSavedAt(Date.now()); }
  }, [site]); // eslint-disable-line react-hooks/exhaustive-deps
  const refused = state.notice?.action === "GRAPH_SAVE" ? state.notice : undefined;
  useEffect(() => { setSaving(false); }, [refused?.at]);

  const tapNode = (e: PointerEvent, id: string) => {
    if (!draft) return;
    e.stopPropagation();
    if (tool === "delete") setDraft(removeNode(draft, id));
    else if (tool === "connect") {
      if (linkFrom) setDraft(addEdge(draft, linkFrom, id));
      setLinkFrom(id);
    } else if (tool === "move") {
      dragging.current = id;
      paneRef.current!.setPointerCapture(e.pointerId);
    }
  };

  const local = (e: { clientX: number; clientY: number }) => {
    const b = paneRef.current!.getBoundingClientRect();
    return [e.clientX - b.left, e.clientY - b.top] as const;
  };
  const down = (e: PointerEvent) => { press.current = { x: e.clientX, y: e.clientY, px: pan[0], py: pan[1], moved: false }; };
  const move = (e: PointerEvent) => {
    if (draft && dragging.current) {
      const { x, y } = toWorld(...local(e));
      setDraft(moveNode(draft, dragging.current, x, y));
      return;
    }
    const d = press.current;
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (Math.abs(dx) + Math.abs(dy) > 8) d.moved = true;
    if (d.moved) setPan([d.px + dx, d.py + dy]);
  };
  const up = (e: PointerEvent) => {
    dragging.current = null;
    const d = press.current;
    press.current = null;
    if (!d || d.moved) return;
    const p = toWorld(...local(e));
    if (draft) {
      if (tool === "add") setDraft(addNode(draft, p.x, p.y, nodes[0]?.map_id ?? models.find((r) => r.protocol === "vda5050" && r.pose)?.pose?.map_id ?? "site"));
      return;
    }
    if (keyOpen) { setKeyOpen(false); return; }
    if (ui.send && sel) ui.setSend(planFor(sel, p));
  };
  const stopEv = (e: PointerEvent) => e.stopPropagation();

  // ---- what goes where: robots first, then node names; nothing overlaps -----
  const placed = robots.filter((v) => v.r.pose);
  const send = ui.send;
  const mapTools = !editing && !send && !(drive && phone) && !sheetOpen;
  const canEdit = access.admin && !!site?.editable;
  const boxes: Box[] = [];
  const hit = (b: Box) => boxes.some((o) => b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y);
  if (sheetOpen) boxes.push({ x: mw - 162, y: 8, w: 162, h: 56 });
  const off = !phone && !editing && !send ? placed.filter((v) => { const x = X(v.r.pose!.x), y = Y(v.r.pose!.y); return x < 0 || x > mw || y < 0 || y > visH; }).length : 0;
  if (off) boxes.push({ x: 0, y: 8, w: 260, h: 56 });
  if (editing) boxes.push({ x: 0, y: 0, w: mw, h: 76 }, { x: 0, y: visH - 52, w: 460, h: 52 });
  const clusterW = canEdit ? 320 : 224;
  if (mapTools) boxes.push({ x: mw - 12 - clusterW, y: 8, w: clusterW + 12, h: 56 });
  if (mapTools && keyOpen) boxes.push({ x: mw - 312, y: 60, w: 312, h: 180 });

  const order = [...placed].sort((a, b) => Number(b.r.name === ui.sel) - Number(a.r.name === ui.sel) || Number(b.key !== "ok") - Number(a.key !== "ok"));
  order.forEach((v) => boxes.push({ x: X(v.r.pose!.x) - 16, y: Y(v.r.pose!.y) - 16, w: 32, h: 32 }));
  const labels: Label[] = [];
  const staleAge = (v: RobotView) => (v.r.last_seen ? ` · ${Math.round(ctx.now / 1000 - v.r.last_seen)} s` : "");
  order.forEach((v) => {
    const x = X(v.r.pose!.x), y = Y(v.r.pose!.y), mine = v.r.name === ui.sel;
    const text = (v.key === "ok" && !v.unconfirmed ? "" : `${v.glyph} `) + v.r.name + (v.driven ? ` · ${v.r.driver}` : "") + (v.key === "stale" ? staleAge(v) : "");
    const w = text.length * 7.3 + 14, h = 20;
    const tries = [[x - w / 2, y + 20], [x - w / 2, y - 20 - h], [x + 20, y - h / 2], [x - 20 - w, y - h / 2]].map(([a, b]) => ({ x: a, y: b, w, h }));
    const b = tries.find((q) => !hit(q)) ?? tries[0];
    boxes.push(b);
    labels.push({ ...b, text, color: v.unconfirmed ? "var(--fault-fg)" : v.key === "ok" ? "var(--text-1)" : `var(--${v.key === "warn" ? "warn-fg" : v.key === "fault" ? "fault-fg" : "text-3"})`,
      bg: "var(--bg)", border: mine ? "var(--accent)" : "var(--line-strong)", weight: 600, pad: 6, opacity: focus && !mine ? 0.5 : 1, z: mine ? 5 : 3 });
  });
  nodes.forEach((n) => boxes.push({ x: X(n.x) - 5, y: Y(n.y) - 5, w: 10, h: 10 }));
  nodes.forEach((n) => {
    const a = X(n.x), b = Y(n.y), text = n.name ?? n.id, w = text.length * 7.3 + 6, h = 16;
    const tries = [[a + 7, b - 7 - h], [a + 7, b + 5], [a - 7 - w, b - 7 - h], [a - 7 - w, b + 5]].map(([q, r]) => ({ x: q, y: r, w, h }));
    const box = tries.find((q) => !hit(q) && q.x > 4 && q.x + q.w < mw - 4 && q.y > 4 && q.y + q.h < visH - 4);
    if (!box) return;
    boxes.push(box);
    labels.push({ ...box, text, color: "var(--text-2)", bg: "var(--map-floor)", border: "transparent", weight: 500, pad: 3, opacity: focus ? 0.6 : 1, z: 1 });
  });

  const scaleM = [1, 2, 5, 10, 20, 50].find((m) => m * sc >= 70) ?? 100;
  const emTone = refused ? (refused.text === GRAPH_CHANGED ? "warn" : "fault") : "ok";
  const justSaved = !editing && savedAt > 0 && ctx.now - savedAt < 6000;
  const em = refused && editing ? (refused.text === GRAPH_CHANGED
    ? { g: "▲", t: GRAPH_CHANGED, b: "Someone else saved first. Your draft is kept until you reload.", a: "Reload" }
    : refused.text.startsWith("Can't write")
      ? { g: "◆", t: "Can't save: the graph folder is read-only", b: `${refused.text} Your draft is kept.`, a: "" }
      : { g: "◆", t: "Graph not saved", b: refused.text, a: "" })
    : justSaved ? { g: "✓", t: "Graph saved", b: models.some((r) => r.task.state === "active") ? "Orders already running keep their old route." : "New orders use the updated graph.", a: "" } : null;
  const robotNotice = !editing && state.notice?.action === "OPERATOR_STOP_ALL" ? state.notice.text : "";
  const scaleBottom = drive && phone ? Math.round(mh - visH + 8) : sheetOn ? (ui.sheetH || 250) + 12 : send && !phone ? 104 : 12 + (editing ? 42 : 0) + (em ? 84 : 0);
  const cover: CSSProperties = { opacity: focus ? 0.6 : 1 };
  const confirmStyle: CSSProperties = phone && sel ? { top: 12 } : { bottom: 12 };
  const picking = send?.step === "pick";
  const pickVda = picking && sel?.protocol === "vda5050";

  return (
    <div ref={paneRef} className={`mappane ${editing ? "is-editing" : ""} ${send ? "is-sending" : ""}`} data-testid="map-pane" onPointerDown={down} onPointerMove={move} onPointerUp={up}>
      <svg className="sitemap" data-testid="site-map" width={mw} height={mh} role="img" aria-label="Site map with robots">
        {!bg && <rect className="sitemap__plain" style={cover} x={X(B.x0)} y={Y(B.y1)} width={bw * sc} height={bh * sc} />}
        {bg && size && (
          <image className="sitemap__floor" href={bg.url} preserveAspectRatio="none" style={cover} x={X(bg.origin[0])} y={Y(bg.origin[1] + size[1] * bg.scale)} width={size[0] * bg.scale * sc} height={size[1] * bg.scale * sc} />
        )}
        {edges.map((e) => {
          const a = byId.get(e.start), b = byId.get(e.end);
          if (!a || !b) return null;
          const x1 = X(a.x), y1 = Y(a.y), x2 = X(b.x), y2 = Y(b.y);
          return (
            <g key={e.id} data-edge={e.id} data-directed={e.directed ? "true" : undefined}>
              <line className="sitemap__edge" x1={x1} y1={y1} x2={x2} y2={y2} style={{ stroke: editing ? "var(--accent)" : undefined, strokeOpacity: editing ? 0.7 : focus ? 0.6 : 1 }} />
              {e.directed && <path d="M-6,-5 L6,0 L-6,5 Z" fill="var(--map-node)" transform={`translate(${(x1 + x2) / 2} ${(y1 + y2) / 2}) rotate(${(Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI})`} />}
              {editing && tool === "delete" && (
                <line className="sitemap__hit" x1={x1} y1={y1} x2={x2} y2={y2} strokeWidth={24} onPointerDown={(ev) => { ev.stopPropagation(); setDraft(removeEdge(draft!, e.id)); }} />
              )}
            </g>
          );
        })}
        {robots.map((v) => {
          const r = v.r;
          if (!r.pose) return null;
          const route = r.task.route.map((id) => byId.get(id)).filter((n): n is GraphNode => !!n);
          const goal = route[route.length - 1] ?? (r.command?.action === "GOAL" && r.command.point && r.task.state === "active" ? { x: r.command.point[0], y: r.command.point[1] } : null);
          if (!goal) return null;
          const mine = r.name === ui.sel, held = r.paused || !!r.stop;
          const op = held ? 0.35 : focus && !mine ? 0.3 : 0.9;
          const color = mine ? "var(--accent)" : "var(--text-2)";
          return (
            <g key={`route-${r.id}`} className="sitemap__route" opacity={op} data-route={r.name}>
              {route.length > 0 && <polyline points={[`${X(r.pose.x)},${Y(r.pose.y)}`, ...route.map((n) => `${X(n.x)},${Y(n.y)}`)].join(" ")} fill="none" stroke={color} strokeWidth={mine ? 4 : 2.5} strokeDasharray={held ? "6 6" : undefined} strokeLinejoin="round" strokeLinecap="round" />}
              <circle cx={X(goal.x)} cy={Y(goal.y)} r={10} fill="none" stroke={color} strokeWidth={2} />
              <circle cx={X(goal.x)} cy={Y(goal.y)} r={3} fill={color} />
            </g>
          );
        })}
        {send?.path && (
          <g>
            <polyline points={send.path.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")} fill="none" stroke="var(--accent)" strokeWidth={4} strokeDasharray="2 8" strokeLinecap="round" />
            <circle cx={X(send.path[send.path.length - 1][0])} cy={Y(send.path[send.path.length - 1][1])} r={14} fill="var(--accent-bg)" stroke="var(--accent)" strokeWidth={3} />
          </g>
        )}
        {nodes.map((n) => (
          <g key={n.id} data-node={n.id} data-name={n.name}>
            <circle className={`sitemap__node ${linkFrom === n.id ? "is-from" : ""}`} cx={X(n.x)} cy={Y(n.y)} r={editing ? 7 : 4.5} style={{ stroke: editing ? "var(--accent)" : undefined }} />
            {pickVda && <circle cx={X(n.x)} cy={Y(n.y)} r={12} fill="none" stroke="var(--accent)" strokeWidth={2} />}
            {editing && <circle className="sitemap__halo" cx={X(n.x)} cy={Y(n.y)} r={22} />}
            {/* A finger needs more than the dot. */}
            {editing && <circle className="sitemap__hit" cx={X(n.x)} cy={Y(n.y)} r={22} onPointerDown={(ev) => tapNode(ev, n.id)} />}
          </g>
        ))}
      </svg>
      {labels.map((l, i) => (
        <span key={i} className="maplabel" style={{ left: Math.round(l.x), top: Math.round(l.y), height: l.h, padding: `0 ${l.pad}px`, color: l.color, background: l.bg, borderColor: l.border, fontWeight: l.weight, opacity: l.opacity, zIndex: l.z }}>{l.text}</span>
      ))}
      {placed.map((v) => {
        const r = v.r, mine = r.name === ui.sel;
        const dimmed = focus && !mine;
        const inner = v.key === "offline" ? "⊘" : v.paused || r.stop === "stopped" ? "❚❚" : v.driven ? "◎" : "";
        return (
          <button key={r.id} type="button" className={`marker ${editing ? "is-inert" : ""}`} data-robot={r.name} data-marker={v.key} aria-label={r.name}
            style={{ left: X(r.pose!.x), top: Y(r.pose!.y), opacity: dimmed ? 0.45 : v.key === "stale" ? 0.8 : v.key === "offline" ? 0.75 : 1, zIndex: mine ? 4 : 2 }}
            onPointerDown={stopEv} onPointerUp={stopEv} onClick={() => ui.select(r.name)}>
            <Marker protocol={r.protocol} kind={v.key} selected={mine} unconfirmed={v.unconfirmed} outline={r.off_graph != null} heading={(-r.pose!.theta * 180) / Math.PI} />
            <span className="marker__inner">{inner}</span>
          </button>
        );
      })}

      {editing && (
        <div className="maptop" onPointerDown={stopEv} onPointerUp={stopEv} role="toolbar" aria-label="Edit the node graph">
          <span className="maptop__label">Editing graph</span>
          <div className="maptools">
            {TOOLS.map(([key, label]) => (
              <button key={key} type="button" className={tool === key ? "is-on" : ""} aria-pressed={tool === key} data-testid={`tool-${key}`} onClick={() => { setTool(key); setLinkFrom(null); }}>{label}</button>
            ))}
          </div>
          <span className="spacer" />
          <div className="maptop__end">
            <button type="button" className="btn-map" onClick={stopEdit}>Discard</button>
            <button type="button" className="btn-map btn-map--solid" data-testid="save-graph" disabled={saving} onClick={save}>Save graph</button>
          </div>
        </div>
      )}
      {(editing || em || robotNotice) && (
        <div className="mapbottom">
          {editing && <span className="maphint" data-testid="graph-count">{TOOLS.find(([k]) => k === tool)![2]} {draft!.nodes.length} nodes, {draft!.edges.length} edges.</span>}
          {em && (
            <div className={`mapmsg mapmsg--${emTone}`} data-testid={refused && editing ? "graph-error" : "graph-saved"} onPointerDown={stopEv} onPointerUp={stopEv}>
              <span className="mapmsg__title"><span className="mono">{em.g}</span>{em.t}</span>
              <span className="mapmsg__body">{em.b}</span>
              {em.a && <button type="button" className="btn-small" onClick={stopEdit}>{em.a}</button>}
            </div>
          )}
          {robotNotice && <span className="maphint tone-warn" data-testid="graph-error">{robotNotice}</span>}
        </div>
      )}

      {mapTools && (
        <div className="mapcluster" onPointerDown={stopEv} onPointerUp={stopEv}>
          <div className="maptools">
            <button type="button" className="maptools__sq" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.5, z / 1.25))}>−</button>
            <button type="button" className="maptools__sq" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(3, z * 1.25))}>+</button>
            <button type="button" data-testid="fit-all" onClick={() => { setZoom(1); setPan([0, 0]); setFitAll(true); }}>Fit all</button>
            <button type="button" aria-expanded={keyOpen} className={keyOpen ? "is-open" : ""} data-testid="map-key" onClick={() => setKeyOpen(!keyOpen)}>Key</button>
            {canEdit && <button type="button" data-testid="edit-graph" onClick={startEdit}>Edit graph</button>}
          </div>
          {keyOpen && (
            <div className="mapkey" data-testid="key-panel">
              {KEY.map((k) => (
                <span key={k.label} className="mapkey__item">
                  <span className="mapkey__mark"><Marker protocol={k.protocol} kind={k.kind} outline={k.outline} size={36} heading={-30} /><span className="marker__inner marker__inner--sm">{k.inner}</span></span>
                  {k.label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {sheetOpen && !send && (
        <button type="button" className="mapchip mapchip--right" onPointerDown={stopEv} onPointerUp={stopEv} onClick={() => { setPan([0, 0]); setZoom(1); }}>Center on robot</button>
      )}
      {off > 0 && (
        <button type="button" className="mapchip" data-testid="off-screen" onPointerDown={stopEv} onPointerUp={stopEv} onClick={() => { setZoom(1); setPan([0, 0]); setFitAll(true); }}>{off} robot{off > 1 ? "s" : ""} off-screen · Fit all</button>
      )}
      <div className="mapscale" style={{ bottom: scaleBottom }}>
        <span className="mono">{scaleM} m</span>
        <span className="mapscale__bar" style={{ width: Math.round(scaleM * sc) }} />
      </div>

      {send && sel && (
        <div className="confirm" style={confirmStyle} onPointerDown={stopEv} onPointerUp={stopEv}>
          {picking ? (
            <>
              <div className="confirm__text">
                <span className="confirm__kicker">SEND {sel.name.toUpperCase()}</span>
                <span className="confirm__pick">{sel.protocol === "ros2" ? "Tap a point on the map" : "Tap a node. Taps snap to the nearest node."}</span>
              </div>
              <button type="button" className="btn-outline" onClick={() => ui.setSend(null)}>Cancel</button>
            </>
          ) : (
            <>
              <div className="confirm__text">
                <span className="confirm__kicker">CONFIRM</span>
                <span className="confirm__big">Send <span className="mono">{sel.name}</span> to {send.dest}</span>
                <span className="mono small text-2">{send.via}</span>
              </div>
              <div className="confirm__btns">
                <button type="button" className="btn-outline btn-outline--tall" onClick={() => ui.setSend(null)}>Cancel</button>
                <button type="button" className="btn-send" data-testid="send-goal" onClick={doSend}>Send</button>
              </div>
            </>
          )}
        </div>
      )}
      {(site?.problems ?? []).map((p) => <p key={p} className="mapproblem" role="alert">{p}</p>)}
    </div>
  );
}
