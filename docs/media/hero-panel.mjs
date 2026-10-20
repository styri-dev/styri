// Record the Styri panel while the terminal recording runs the commands.
import { chromium } from "@playwright/test";
import { writeFileSync } from "node:fs";
const [w, h, seconds] = [1000, 620, 19];
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: w, height: h }, recordVideo: { dir: "video", size: { width: w, height: h } } });
writeFileSync("panel.start", String(Date.now() / 1000));
const page = await context.newPage();
const end = Date.now() + seconds * 1000;
while (Date.now() < end) {
  try {
    await page.goto("http://localhost:8080/", { timeout: 1000 });
    writeFileSync("panel.loaded", String(Date.now() / 1000));
    break;
  } catch { await new Promise((r) => setTimeout(r, 150)); }
}
await page.waitForTimeout(Math.max(0, end - Date.now()));
await context.close();
await browser.close();
