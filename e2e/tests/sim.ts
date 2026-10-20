import { execSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// How to run a command next to the sim robot. Locally that is the compose
// service; CI sets SIM_EXEC to a `kubectl exec` into the sim pod.
const SIM_EXEC = process.env.SIM_EXEC ?? "docker compose exec -T sim /ros_entrypoint.sh";
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

function sim(args: string): string {
  return execSync(`${SIM_EXEC} python3 -m styri_sim ${args}`, {
    cwd: REPO,
    encoding: "utf8",
    timeout: 30_000,
  }).trim();
}

export function fault(name: string): void {
  sim(`fault ${name}`);
}

export interface Pose {
  x: number;
  y: number;
  v: number;
  w: number;
}

export function pose(): Pose {
  const lines = sim("pose").split("\n");
  return JSON.parse(lines[lines.length - 1]);
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
