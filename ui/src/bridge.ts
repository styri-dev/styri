// WebSocket client for the Styri bridge (same origin, /ws). See README "Protocol".
import { useCallback, useEffect, useRef, useState } from "react";

export type ConnState = "connecting" | "open" | "closed";
export type Level = "ok" | "warn" | "fault";
export type Health = Level | "unknown";

export interface Hello {
  version: string;
  robot: string;
  domain: string;
  stale_after: number;
  controls: boolean;
  min_voltage: number | null; // battery.min_voltage / STYRI_MIN_VOLTAGE, if set
  config?: ConfigSummary;
  robots?: { index: number; name: string; domain: string; namespace: string | null; protocol?: Protocol }[];
  not_shown?: NotShown[];
  site?: Site;
  control?: ControlStatus; // absent with control off: the panel is view-only
}

export type Protocol = "ros2" | "vda5050";

/** A robot in the file, over the cap. */
export interface NotShown {
  name: string;
  protocol: Protocol;
  reason: string;
  link: string;
}

export interface ControlStatus {
  enabled: boolean;
  logged_in: boolean;
  needs_setup: boolean;
  session_hours: number;
  stop_requires_login: boolean;
}

export interface Capabilities {
  can_teleop: boolean;
  can_waypoint: boolean;
  can_pause: boolean;
  can_cancel: boolean;
  can_stop: boolean;
}

export interface Pose {
  x: number;
  y: number;
  theta: number;
  map_id: string;
}

/** The unified robot model: the same for every protocol. */
export interface RobotModel {
  index: number;
  id: string;
  name: string;
  protocol: Protocol;
  vendor: string | null;
  model: string | null;
  verdict: "OK" | "WARNING" | "FAULT" | "NO DATA";
  reason: string;
  battery: number | null;
  voltage: number | null;
  errors: { type: string; level: string; description: string }[];
  warnings: string[];
  last_seen: number | null; // unix seconds
  stale: boolean;
  pose: Pose | null;
  velocity: { linear: number; angular: number } | null;
  driving: boolean | null;
  paused: boolean;
  task: { id: string | null; state: "idle" | "active" | "paused" | "failed" | "done"; last_node: string | null; route: string[] };
  capabilities: Capabilities;
  limits: { max_linear: number; max_angular: number };
  points: string[];
  vehicle_stop: boolean;
  factsheet: Record<string, any> | null;
}

export interface GraphNode {
  id: string;
  x: number;
  y: number;
  map_id: string;
}

export interface Site {
  graph: { nodes: GraphNode[]; edges: { id: string; start: string; end: string }[] } | null;
  background: { url: string; scale: number; origin: [number, number] } | null;
  version: string | null; // changes with the graph: a stale save is refused
  editable: boolean; // site.graph is set, so the editor has a file to save
  problems: string[];
}

export interface AuditRow {
  id: number;
  time: string;
  kind: "command" | "command_rejected";
  client: string | null;
  user: string | null;
  command: string;
  robot?: string | null;
  reason?: string;
  payload?: Record<string, unknown>;
}

/** Where the topic mapping came from (hello.config). */
export interface ConfigSummary {
  source: string; // the styri.yaml path, or "environment"
  error: string | null; // the file couldn't be used; environment defaults apply
  notes: string[];
  robots_in_file: number;
  namespace: string | null;
  domain: string;
  stale_after: number;
  host_fallback: boolean;
}

export type ValueKind = "number" | "text" | "bool";

export interface Tile {
  value: number | string | boolean | null;
  age: number | null;
  source: string | null;
  level: Level;
  stale: boolean;
  label: string | null; // e.g. "CPU temp", or "Styri host CPU" when that's the source
  unit: string;
  kind: ValueKind;
  mapped: boolean; // false when the mapping turns this tile off
  key?: string;
}

export type MappingStatus = "ok" | "waiting" | "missing" | "error" | "stale";

/** One mapping and whether it works, for the banner and the Configuration view. */
export interface MappingRow {
  key: string;
  label: string;
  topic: string | null; // null: the Styri machine's own sensor
  where: string; // "topic · field path", readable
  status: MappingStatus;
  detail: string;
  suggestions: string[];
  type?: string | null;
  value?: number | string | boolean | null;
  unit?: string;
  kind?: ValueKind;
  stale_after?: number;
}

export interface TopicRow {
  name: string;
  type: string;
  hz: number;
  age: number | null;
  stale: boolean;
  supported: boolean;
}

export interface Snapshot {
  robot: string;
  robot_index?: number;
  domain: string;
  robot_found: boolean;
  health: { level: Health; line: string };
  battery: Tile;
  voltage: Tile;
  cpu_temp: Tile;
  status: Tile | null; // the robot's own status, when mapped
  fields: Tile[]; // custom fields, up to 5
  mappings: MappingRow[];
  last_message: { age: number | null; topic: string | null };
  topics: TopicRow[];
  seen: string[];
  host: { load_pct: number | null };
}

export type EventKind = "connection" | "state" | "warning";

export interface ActivityEvent {
  id: number;
  ts: number; // unix seconds
  kind: EventKind;
  msg: string;
  source: string;
}

export interface TopicMessage {
  topic: string;
  robot_index?: number;
  msg_type?: string;
  text?: string | null;
  note?: string | null;
  error?: string;
}

export interface History {
  cpuTemp: number[];
  load: number[];
} // last HISTORY snapshots, oldest first

export interface BridgeState {
  conn: ConnState;
  hello?: Hello;
  // Per robot index: Styri Core shows one robot (index 0).
  snapshots: Record<number, Snapshot>;
  snapshotAt: Record<number, number>; // Date.now() when each robot's last snapshot arrived
  history: Record<number, History>;
  events: ActivityEvent[];
  latencyMs?: number;
  retryAt?: number; // Date.now() of the next reconnect attempt
  message?: TopicMessage;
  fleet: RobotModel[];
  control?: ControlStatus;
  authError?: string;
  notice?: { text: string; robot?: string | null; at: number }; // the bridge refused a command
  audit: AuditRow[];
}

const NO_HISTORY: History = { cpuTemp: [], load: [] };

/** One robot's slice of the state. */
export function forRobot(state: BridgeState, robot: number) {
  return { snapshot: state.snapshots[robot], snapshotAt: state.snapshotAt[robot], history: state.history[robot] ?? NO_HISTORY };
}

const MAX_EVENTS = 5000;
const HISTORY = 48;

const push = (arr: number[], v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? arr : [...arr.slice(-(HISTORY - 1)), v];
const PING_EVERY_MS = 2000;

export function bridgeUrl(): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws`;
}

export function useBridge(url: string) {
  const [state, setState] = useState<BridgeState>({ conn: "connecting", events: [], snapshots: {}, snapshotAt: {}, history: {}, fleet: [], audit: [] });
  const wsRef = useRef<WebSocket | null>(null);
  const connectNow = useRef<() => void>(() => {});

  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let stopPing = () => {};
    let backoff = 1000;

    const connect = () => {
      clearTimeout(retry);
      let ping: ReturnType<typeof setInterval> | undefined;
      setState((s) => ({ ...s, conn: "connecting", retryAt: undefined }));
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        backoff = 1000;
        setState((s) => ({ ...s, conn: "open" }));
        const sendPing = () => ws.readyState === WebSocket.OPEN &&
          ws.send(JSON.stringify({ action: "PING", t: performance.now() }));
        sendPing();
        ping = setInterval(sendPing, PING_EVERY_MS);
        stopPing = () => clearInterval(ping);
      };

      ws.onmessage = (ev) => {
        let msg: any;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        switch (msg.type) {
          case "hello":
            setState((s) => ({ ...s, hello: msg, control: msg.control }));
            break;
          case "fleet":
            setState((s) => ({ ...s, fleet: msg.robots }));
            break;
          case "site": // someone saved the node graph
            setState((s) => ({ ...s, hello: s.hello && { ...s.hello, site: msg.site } }));
            break;
          case "auth":
            // The cookie is HttpOnly, so the bridge sets it: a reload stays logged in.
            if (msg.ticket) void fetch(`/api/session?ticket=${encodeURIComponent(msg.ticket)}`, { cache: "no-store" });
            setState((s) => ({ ...s, control: msg.control, authError: msg.error }));
            break;
          case "error":
            if (msg.action !== "AUDIT") setState((s) => ({ ...s, notice: { text: msg.error, robot: msg.robot, at: Date.now() } }));
            break;
          case "ack":
            setState((s) => ({ ...s, notice: undefined }));
            break;
          case "audit":
            setState((s) => ({ ...s, audit: msg.rows }));
            break;
          case "snapshot": {
            const i: number = msg.robot_index ?? 0;
            setState((s) => {
              const h = s.history[i] ?? NO_HISTORY;
              const cpu = typeof msg.cpu_temp?.value === "number" ? msg.cpu_temp.value : null;
              return {
                ...s, snapshots: { ...s.snapshots, [i]: msg }, snapshotAt: { ...s.snapshotAt, [i]: Date.now() },
                history: { ...s.history, [i]: { cpuTemp: push(h.cpuTemp, cpu), load: push(h.load, msg.host?.load_pct) } },
              };
            });
            break;
          }
          case "activity": // full history on (re)connect, newest first
            setState((s) => ({ ...s, events: msg.events }));
            break;
          case "event":
            setState((s) => ({ ...s, events: [msg.event, ...s.events].slice(0, MAX_EVENTS) }));
            break;
          case "pong":
            setState((s) => ({ ...s, latencyMs: Math.max(1, Math.round(performance.now() - msg.t)) }));
            break;
          case "message":
            setState((s) => ({ ...s, message: msg }));
            break;
        }
      };

      ws.onclose = () => {
        clearInterval(ping);
        if (closed || wsRef.current !== ws) return; // unmounted, or replaced by "Retry now"
        wsRef.current = null;
        setState((s) => ({ ...s, conn: "closed", latencyMs: undefined, retryAt: Date.now() + backoff }));
        retry = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 10_000);
      };
    };

    connectNow.current = () => {
      backoff = 1000;
      const old = wsRef.current;
      wsRef.current = null;
      old?.close();
      connect();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      stopPing();
      wsRef.current?.close();
    };
  }, [url]);

  const select = useCallback((topic: string, robot = 0) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ action: "SELECT", topic, robot }));
  }, []);

  /** Send a command. With control off, the bridge refuses everything but PING and SELECT. */
  const send = useCallback((payload: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  }, []);

  const retryNow = useCallback(() => connectNow.current(), []);

  return { state, select, send, retryNow };
}

/** Re-render periodically so ages and the clock tick without new data. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}
