import { expect, type Page, test } from "@playwright/test";

// Needs e2e/mixed-fleet/editor.yaml: a graph file Styri can write, starting empty.
test.skip(!process.env.E2E_EDITOR, "needs the writable graph");
test.describe.configure({ mode: "serial" });

const PASSWORD = process.env.STYRI_ADMIN_PASSWORD ?? "styri-demo";

async function login(page: Page) {
  await page.goto("/#map");
  await page.getByTestId("log-in").click();
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).last().click();
  await expect(page.getByTestId("user-menu")).toBeVisible();
}

async function spot(page: Page, fx: number, fy: number): Promise<[number, number]> {
  const b = (await page.getByTestId("site-map").boundingBox())!;
  return [b.x + b.width * fx, b.y + b.height * fy];
}

const node = (page: Page, id: string) => page.locator(`[data-node="${id}"] .sitemap__hit`);

test("no Edit graph without a login", async ({ page }) => {
  await page.goto("/#map");
  await expect(page.getByTestId("site-map")).toBeVisible();
  await expect(page.getByTestId("edit-graph")).toHaveCount(0);
});

test("draw a graph, move a node, delete one, save, and it's there after a reload", async ({ page }) => {
  await login(page);
  await page.getByTestId("edit-graph").click();
  await page.getByTestId("tool-add").click();
  for (const [fx, fy] of [[0.3, 0.3], [0.7, 0.3], [0.7, 0.7]]) await page.mouse.click(...(await spot(page, fx, fy)));
  await expect(page.locator("[data-node]")).toHaveCount(3);

  await page.getByTestId("tool-connect").click();
  for (const id of ["n1", "n2", "n3"]) await node(page, id).click();
  await expect(page.locator("[data-edge]")).toHaveCount(2);

  await page.getByTestId("tool-move").click();
  const b = (await node(page, "n3").boundingBox())!;
  const before = await page.locator('[data-node="n3"] circle').first().getAttribute("cx");
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2 - 120, b.y + b.height / 2, { steps: 6 });
  await page.mouse.up();
  expect(await page.locator('[data-node="n3"] circle').first().getAttribute("cx")).not.toBe(before);

  await page.getByTestId("tool-add").click();
  await page.mouse.click(...(await spot(page, 0.2, 0.8)));
  await page.getByTestId("tool-delete").click();
  await node(page, "n4").click();
  await expect(page.locator("[data-node]")).toHaveCount(3);

  await page.getByTestId("save-graph").click();
  await expect(page.getByTestId("edit-graph")).toBeVisible();

  await page.reload();
  await expect(page.locator("[data-node]")).toHaveCount(3);
  await expect(page.locator("[data-edge]")).toHaveCount(2);
});

test("deleting a node takes its edges; Discard changes nothing", async ({ page }) => {
  await login(page);
  await page.getByTestId("edit-graph").click();
  await page.getByTestId("tool-delete").click();
  await node(page, "n2").click();
  await expect(page.locator("[data-edge]")).toHaveCount(0);
  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.locator("[data-node]")).toHaveCount(3);
  await expect(page.locator("[data-edge]")).toHaveCount(2);
});

test("a saved graph takes orders at once: a vehicle drives a route it didn't have before", async ({ page }) => {
  await login(page);
  // Under the vehicle's real start, so its order begins where it stands.
  const graph = {
    nodes: [{ id: "n1", x: 2, y: 2, map_id: "plant-a" }, { id: "n2", x: 5, y: 2, map_id: "plant-a" }, { id: "n3", x: 5, y: 5, map_id: "plant-a" }],
    edges: [{ id: "e1", start: "n1", end: "n2" }, { id: "e2", start: "n2", end: "n3" }],
  };
  const replies = await page.evaluate(async ([g, password]) => {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    await new Promise((r) => (ws.onopen = r));
    const got: any[] = [];
    ws.onmessage = (e) => { const m = JSON.parse(e.data); if (["ack", "error"].includes(m.type)) got.push(m); };
    const wait = (n: number) => new Promise<void>((r) => { const t = setInterval(() => { if (got.length >= n) { clearInterval(t); r(); } }, 50); });
    let version: string | null = null;
    const auth = new Promise((r) => ws.addEventListener("message", (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "hello") version = m.site.version;
      if (m.type === "auth") r(0);
    }));
    ws.send(JSON.stringify({ action: "LOGIN", password }));
    await auth;
    ws.send(JSON.stringify({ action: "GRAPH_SAVE", graph: g, version }));
    await wait(1);
    ws.send(JSON.stringify({ action: "GOAL", robot: "agv-07", node: "n3" }));
    await wait(2);
    ws.close();
    return got;
  }, [graph, PASSWORD] as const);
  expect(replies.map((r) => r.type)).toEqual(["ack", "ack"]);
  await page.goto("/#fleet");
  await expect(page.locator('.ftile[data-robot="agv-07"]')).toHaveAttribute("data-task", "active", { timeout: 10_000 });
});

test("connecting two nodes again makes the edge one-way, with an arrow", async ({ page }) => {
  await login(page);
  await page.getByTestId("edit-graph").click();
  await page.getByTestId("tool-connect").click();
  await node(page, "n1").click();
  await node(page, "n2").click(); // already joined
  await expect(page.locator('[data-edge][data-directed="true"] path')).toHaveCount(1);
  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.locator('[data-edge][data-directed="true"]')).toHaveCount(0);
});

test("two editors: the second to save is told to reload, and keeps its draft", async ({ browser }) => {
  const one = await (await browser.newContext()).newPage();
  const two = await (await browser.newContext()).newPage();
  for (const page of [one, two]) {
    await login(page);
    await page.getByTestId("edit-graph").click();
    await page.getByTestId("tool-add").click();
  }
  await one.mouse.click(...(await spot(one, 0.2, 0.2)));
  await one.getByTestId("save-graph").click();
  await expect(one.getByTestId("edit-graph")).toBeVisible();
  await two.mouse.click(...(await spot(two, 0.8, 0.8)));
  await two.getByTestId("save-graph").click();
  await expect(two.getByTestId("graph-error")).toContainText("The graph changed since you opened it. Reload.");
  await expect(two.getByTestId("save-graph")).toBeVisible();
});

test("at 390 px the toolbar fits and the map doesn't scroll while editing", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByTestId("edit-graph").click();
  expect(await page.getByTestId("site-map").evaluate((e) => getComputedStyle(e).touchAction)).toBe("none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  await expect(page.getByTestId("save-graph")).toBeInViewport();
});
