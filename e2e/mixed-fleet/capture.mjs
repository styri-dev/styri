// Drive the panel through the mixed-fleet story and record it, for the proof video.
// Run by examples/mixed-fleet/capture.sh. Writes frames and a list for ffmpeg to OUT.
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

const OUT = process.env.OUT ?? "frames";
const PASSWORD = process.env.STYRI_ADMIN_PASSWORD ?? "styri-demo";
const [W, H] = [1280, 720];
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL });
const page = await (await browser.newContext({ viewport: { width: W, height: H } })).newPage();
const cdp = await page.context().newCDPSession(page);
const frames = [];
cdp.on("Page.screencastFrame", ({ data, metadata, sessionId }) => {
  const name = `f${String(frames.length).padStart(5, "0")}.jpg`;
  writeFileSync(`${OUT}/${name}`, Buffer.from(data, "base64"));
  frames.push({ name, t: metadata.timestamp });
  cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
});

const wait = (s) => page.waitForTimeout(s * 1000);
// A visible pointer, since a recording has none.
const pointer = () => page.evaluate(() => {
  if (document.getElementById("cap-pointer")) return;
  const dot = document.createElement("div");
  dot.id = "cap-pointer";
  dot.style.cssText = "position:fixed;z-index:99;width:26px;height:26px;margin:-13px;border-radius:50%;pointer-events:none;"
    + "background:rgba(255,255,255,.35);border:2px solid #fff;left:-40px;top:-40px;transition:transform .12s";
  document.body.append(dot);
  addEventListener("mousemove", (e) => { dot.style.left = `${e.clientX}px`; dot.style.top = `${e.clientY}px`; }, true);
  addEventListener("mousedown", () => { dot.style.transform = "scale(.65)"; }, true);
  addEventListener("mouseup", () => { dot.style.transform = ""; }, true);
});
async function tap(x, y, hold = 0) {
  await page.mouse.move(x, y, { steps: 18 });
  await wait(0.25);
  await page.mouse.down();
  await wait(hold || 0.08);
  await page.mouse.up();
}
async function tapOn(locator, hold = 0) {
  await locator.scrollIntoViewIfNeeded();
  const b = await locator.boundingBox();
  await tap(b.x + b.width / 2, b.y + b.height / 2, hold);
}
// A point on the site map, by its offset in metres from a graph node.
const onMap = (node, dx = 0, dy = 0) => page.evaluate(([id, ox, oy]) => {
  const bar = document.querySelector(".mapscale");
  const perMetre = bar.querySelector(".mapscale__bar").offsetWidth / parseFloat(bar.textContent);
  const box = document.querySelector(`[data-node="${id}"] circle`).getBoundingClientRect();
  return [box.x + box.width / 2 + ox * perMetre, box.y + box.height / 2 - oy * perMetre];
}, [node, dx, dy]);
async function sendTo(robot, node, dx = 0, dy = 0) {
  await tapOn(page.locator(`[data-pick="${robot}"]`)); // by the fleet list: a moving marker is a moving target
  await wait(0.8);
  await tapOn(page.getByRole("button", { name: "Send to…" }).first());
  await wait(0.6);
  await tap(...(await onMap(node, dx, dy)));
  await wait(1);
  await tapOn(page.getByTestId("send-goal"));
  await wait(1.2);
}

await page.goto("http://localhost:8080/#fleet");
await page.locator('.ftile[data-robot="agv-08"]').waitFor();
await wait(3); // every tile fresh
await pointer();
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 85, maxWidth: W, maxHeight: H, everyNthFrame: 1 });

await wait(5); // one panel: a ROS 2 robot and two VDA 5050 vehicles
await tapOn(page.getByRole("link", { name: "Map" }));
await wait(3);
await tapOn(page.getByTestId("log-in"));
await wait(0.6);
await page.getByLabel("Username").pressSequentially("admin", { delay: 60 });
await page.getByLabel("Password").pressSequentially(PASSWORD, { delay: 60 });
await page.keyboard.press("Enter");
await page.getByTestId("user-menu").waitFor();
await wait(1.5);

await sendTo("amr-01", "n3", -0.3, -0.3); // Nav2 plans around the obstacles
await sendTo("agv-07", "n3");             // VDA 5050: snaps to the node, order along the graph
await sendTo("agv-08", "n6");
await wait(2);

await tapOn(page.locator('[data-pick="agv-07"]'));
await wait(1);
await tapOn(page.getByRole("button", { name: "Pause", exact: true }));
await wait(3);
await tapOn(page.getByRole("button", { name: "Resume", exact: true }));
await wait(1);
await wait(3);

await tapOn(page.getByTestId("stop-all"), 1.2); // press and hold
await wait(4);
await tapOn(page.getByRole("link", { name: "Fleet" }));
await wait(4);
await tapOn(page.locator('.ftile[data-robot="agv-07"]'));
await wait(1.5);
await tapOn(page.getByRole("button", { name: "Details" }).first());
await wait(1.5);
await page.getByTestId("factsheet").scrollIntoViewIfNeeded();
await wait(4);
await tapOn(page.getByRole("link", { name: "Activity" }));
await wait(5);

await cdp.send("Page.stopScreencast");
await browser.close();

// ffmpeg's concat list: each frame shows until the next.
const list = frames.map((f, i) => `file '${f.name}'\nduration ${Math.max(0.001, ((frames[i + 1]?.t ?? f.t + 0.5) - f.t)).toFixed(3)}`);
writeFileSync(`${OUT}/list.txt`, `${list.join("\n")}\nfile '${frames.at(-1).name}'\n`);
console.log(`${frames.length} frames, ${(frames.at(-1).t - frames[0].t).toFixed(0)} s`);
