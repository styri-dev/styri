// Every test's setup: VDA 5050 sims back at their start nodes, nothing paused, no task
// running, whatever ran before. A stop can leave a vehicle paused and off the graph, on purpose.
import { execSync } from "node:child_process";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const DEMO = `${dirname(fileURLToPath(import.meta.url))}/../../examples/mixed-fleet`;
const PASSWORD = process.env.STYRI_ADMIN_PASSWORD ?? "styri-demo";
const URL = (process.env.BASE_URL ?? "http://localhost:8080").replace("http", "ws") + "/ws";
const SETTLE_MS = 2200; // past an Operator stop's hold, and the limit on anonymous stops

export async function clean() {
  execSync("docker compose restart -t 1 agv-07 agv-08", { cwd: DEMO, stdio: "ignore", timeout: 30_000 });
  const ws = new WebSocket(URL);
  let robots: any[] = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(String(e.data));
    if (m.type === "fleet") robots = m.robots;
  };
  await new Promise((r) => { ws.onopen = r; });
  ws.send(JSON.stringify({ action: "LOGIN", password: PASSWORD }));
  const dirty = () => robots.filter((r) => r.stale || r.paused || r.driving || ["active", "paused"].includes(r.task.state));
  const deadline = Date.now() + 30_000;
  for (;;) {
    await new Promise((r) => setTimeout(r, 1200)); // a fresh fleet message
    if (robots.length && !dirty().length) break;
    if (Date.now() > deadline) throw new Error(`robots wouldn't settle: ${dirty().map((r) => r.name)}`);
    for (const r of dirty()) {
      if (["active", "paused"].includes(r.task.state) && r.capabilities.can_cancel) ws.send(JSON.stringify({ action: "CANCEL", robot: r.id }));
      if (r.paused && r.capabilities.can_pause) ws.send(JSON.stringify({ action: "RESUME", robot: r.id }));
    }
  }
  ws.close();
  await new Promise((r) => setTimeout(r, SETTLE_MS));
}
