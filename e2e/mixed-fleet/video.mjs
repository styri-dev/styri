// Record the screen parts of the launch video, one folder of frames per shot, at 1920x1080.
// Needs the demo running. TERMINAL is the recorded output of `docker compose up` (JSON).
import { chromium } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

const OUT = process.env.OUT ?? "shots";
const PASSWORD = process.env.STYRI_ADMIN_PASSWORD ?? "styri-demo";
const [W, H] = [1920, 1080];
const PANEL = "http://localhost:8080/";

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL });
const page = await (await browser.newContext({ viewport: { width: W, height: H } })).newPage();
const cdp = await page.context().newCDPSession(page);
const wait = (s) => page.waitForTimeout(s * 1000);

let frames = [], dir = "";
cdp.on("Page.screencastFrame", ({ data, metadata, sessionId }) => {
  const name = `f${String(frames.length).padStart(5, "0")}.jpg`;
  writeFileSync(`${dir}/${name}`, Buffer.from(data, "base64"));
  frames.push({ name, t: metadata.timestamp });
  cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
});
// One shot: `seconds` long however quickly the action finishes.
async function shot(name, seconds, action) {
  dir = `${OUT}/${name}`; frames = [];
  mkdirSync(dir, { recursive: true });
  await pointer();
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
  const start = Date.now();
  await action(async (t) => { const left = t - (Date.now() - start) / 1000; if (left > 0) await wait(left); });
  const left = seconds - (Date.now() - start) / 1000;
  if (left > 0) await wait(left);
  await cdp.send("Page.stopScreencast");
  const list = frames.map((f, i) => `file '${f.name}'\nduration ${Math.max(0.001, (frames[i + 1]?.t ?? f.t + 0.5) - f.t).toFixed(3)}`);
  writeFileSync(`${dir}/list.txt`, `${list.join("\n")}\nfile '${frames.at(-1).name}'\n`);
  console.log(name, frames.length, "frames", ((Date.now() - start) / 1000).toFixed(1), "s");
}
const pointer = () => page.evaluate(() => {
  if (document.getElementById("cap-pointer")) return;
  const dot = document.createElement("div");
  dot.id = "cap-pointer";
  dot.style.cssText = "position:fixed;z-index:99;width:34px;height:34px;margin:-17px;border-radius:50%;pointer-events:none;"
    + "background:rgba(255,255,255,.35);border:2px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.5);left:-40px;top:-40px;transition:transform .12s";
  document.body.append(dot);
  addEventListener("mousemove", (e) => { dot.style.left = `${e.clientX}px`; dot.style.top = `${e.clientY}px`; }, true);
  addEventListener("mousedown", () => { dot.style.transform = "scale(.65)"; }, true);
  addEventListener("mouseup", () => { dot.style.transform = ""; }, true);
});
async function tap(x, y, hold = 0) {
  await page.mouse.move(x, y, { steps: 24 });
  await wait(0.2);
  await page.mouse.down();
  await wait(hold || 0.08);
  await page.mouse.up();
}
async function tapOn(locator, hold = 0) {
  await locator.scrollIntoViewIfNeeded();
  const b = await locator.boundingBox();
  await tap(b.x + b.width / 2, b.y + b.height / 2, hold);
}
const onMap = (node) => page.evaluate((id) => {
  const box = document.querySelector(`[data-node="${id}"] circle`).getBoundingClientRect();
  return [box.x + box.width / 2, box.y + box.height / 2];
}, node);
const pick = (robot) => tapOn(page.locator(`[data-pick="${robot}"]`));
const sendButton = () => page.getByRole("button", { name: "Send to…" }).first();
async function send(robot, node, pause = 0.6) {
  await pick(robot); await wait(pause);
  await tapOn(sendButton()); await wait(pause);
  await tap(...(await onMap(node))); await wait(pause);
  await tapOn(page.getByTestId("send-goal"));
}

// Log in off camera, so the shots start on the panel.
await page.goto(`${PANEL}#map`);
await page.getByTestId("log-in").click();
await page.getByLabel("Username").fill("admin");
await page.getByLabel("Password").fill(PASSWORD);
await page.getByRole("button", { name: "Log in", exact: true }).last().click();
await page.getByTestId("user-menu").waitFor();
await page.getByRole("button", { name: "Got it" }).click().catch(() => {});

// 12–20 s: one command. The output is the real thing, shown at its real order.
const lines = JSON.parse(readFileSync(process.env.TERMINAL, "utf8")).map((l) => l[1]).filter((l) => l.trim() && !l.includes("site-seed"));
await page.setContent(`<!doctype html><body style="margin:0;background:#0b0d10;color:#d7dce2;font:24px/1.45 Menlo,monospace;height:100vh;overflow:hidden;padding:48px;box-sizing:border-box">
  <div id="t" style="white-space:pre-wrap;word-break:break-all"></div></body>`);
await shot("03-terminal", 8, async (at) => {
  await page.evaluate(() => { document.getElementById("t").textContent = "~/styri/examples/mixed-fleet $ "; });
  await at(0.5);
  await page.evaluate(async () => {
    const t = document.getElementById("t");
    for (const c of "docker compose up") { t.textContent += c; await new Promise((r) => setTimeout(r, 45)); }
  });
  await at(1.8);
  await page.evaluate(async (all) => {
    const t = document.getElementById("t");
    for (const l of all) {
      t.textContent += `\n${l}`;
      if (t.scrollHeight > innerHeight - 96) t.textContent = t.textContent.split("\n").slice(-26).join("\n");
      await new Promise((r) => setTimeout(r, 2800 / all.length));
    }
  }, lines.slice(0, 60));
  await at(5);
  await page.goto(`${PANEL}?load#fleet`); // a real load: the hash alone keeps this document
  await pointer();
});

// 20–35 s: every robot on one map; send agv-07.
await page.evaluate(() => { location.hash = "#map"; });
await wait(1.5);
await tapOn(page.getByRole("button", { name: "Fit all" }));
await wait(1);
await shot("04-map-send", 15, async (at) => {
  await at(2);
  await pick("agv-07");
  await at(4);
  await tapOn(sendButton());
  await at(6);
  await tap(...(await onMap("n6")));
  await at(8);
  await tapOn(page.getByTestId("send-goal"));
});

// 35–48 s: drive amr-01.
await shot("05-drive", 13, async (at) => {
  await pick("amr-01");
  await at(1.5);
  await tapOn(page.getByRole("button", { name: "Drive", exact: true }));
  await at(3);
  const b = await page.getByTestId("joystick").boundingBox();
  const [cx, cy] = [b.x + b.width / 2, b.y + b.height / 2];
  await page.mouse.move(cx, cy, { steps: 20 });
  await page.mouse.down();
  await page.mouse.move(cx, cy - b.height * 0.32, { steps: 30 });
  await at(6.5);
  await page.mouse.move(cx + b.width * 0.18, cy - b.height * 0.28, { steps: 30 });
  await at(9.5);
  await page.mouse.up();
});
await page.getByRole("button", { name: "Done driving" }).click();

// 48–60 s: stop agv-08 while it moves.
await send("agv-08", "n4", 0.3);
await wait(1);
await shot("06-stop", 12, async (at) => {
  await pick("agv-08");
  await at(3);
  await tapOn(page.getByTestId("operator-stop"));
  await page.mouse.move(W * 0.45, H * 0.8, { steps: 30 }); // off the label
});

// 60–72 s: stop everything.
await tapOn(page.getByRole("button", { name: "Resume", exact: true }));
await wait(2);
await send("agv-07", "n1", 0.3);
await wait(0.5);
await shot("07-stop-all", 12, async (at) => {
  await at(2.5);
  await tapOn(page.getByTestId("stop-all"), 1.2);
  await page.mouse.move(W * 0.45, H * 0.8, { steps: 30 });
});

// 72–82 s: the log.
await shot("08-activity", 10, async () => {
  await tapOn(page.getByRole("link", { name: "Activity", exact: true }));
});

await browser.close();
