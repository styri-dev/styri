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
  min_voltage: number | null; // STYRI_MIN_VOLTAGE, if set
}

export interface Tile {
  value: number | null;
  age: number | null;
  source: string;
  level: Level;
  stale: boolean;
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
  domain: string;
  robot_found: boolean;
  health: { level: Health; line: string };
  battery: Tile;
  voltage: Tile;
  cpu_temp: Tile;
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
  msg_type?: string;
  text?: string | null;
  note?: string | null;
  error?: string;
}

export interface BridgeState {
  conn: ConnState;
  hello?: Hello;
  snapshot?: Snapshot;
  snapshotAt?: number; // Date.now() when the last snapshot arrived
  events: ActivityEvent[];
  latencyMs?: number;
  retryAt?: number; // Date.now() of the next reconnect attempt
  message?: TopicMessage;
  history: { cpuTemp: number[]; load: number[] }; // last HISTORY snapshots, oldest first
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
  const [state, setState] = useState<BridgeState>({ conn: "connecting", events: [], history: { cpuTemp: [], load: [] } });
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
            setState((s) => ({ ...s, hello: msg }));
            break;
          case "snapshot":
            setState((s) => ({
              ...s, snapshot: msg, snapshotAt: Date.now(),
              history: { cpuTemp: push(s.history.cpuTemp, msg.cpu_temp?.value), load: push(s.history.load, msg.host?.load_pct) },
            }));
            break;
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

  const select = useCallback((topic: string) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ action: "SELECT", topic }));
  }, []);

  const retryNow = useCallback(() => connectNow.current(), []);

  return { state, select, retryNow };
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
