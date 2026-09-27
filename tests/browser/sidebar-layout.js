// Playwright CLI run-code --filename tests/browser/sidebar-layout.js
// Requires a real YouTube watch page with this extension's Digest panel open.
// No provider calls or login automation: tests layout even with unavailable video.
async (page) => {
  const panelSelector = "#youtube-digest-panel";
  const panel = page.locator(panelSelector);
  const handle = page.getByRole("separator", { name: "调整侧栏宽度" });
  const frame = page.frames().find((candidate) => candidate.url().includes("sidepanel.html"));
  if (!frame) throw new Error("Open Digest before running the layout regression");
  await page.setViewportSize({ width: 1280, height: 720 });
  await handle.press("Home");
  const assertFits = async () => {
    await page.waitForFunction(() => {
      const edge = document.querySelector("#youtube-digest-panel").getBoundingClientRect().left;
      return ["#masthead-container", "#movie_player", "video.html5-main-video", ".ytp-chrome-bottom", "ytd-watch-flexy #columns"]
        .every((selector) => {
          const el = document.querySelector(selector);
          return !el || el.getBoundingClientRect().right <= edge + 1;
        });
    }, null, { timeout: 5000 });
  };
  await assertFits();
  const before = await panel.boundingBox();
  const grip = await handle.boundingBox();
  await page.mouse.move(grip.x + grip.width / 2, 250);
  await page.mouse.down();
  await page.mouse.move(grip.x + grip.width / 2 - 120, 250, { steps: 10 });
  await page.mouse.up();
  const wider = await panel.boundingBox();
  if (Math.abs(wider.width - before.width - 120) > 2) throw new Error("Dragging failed to resize sidebar");
  if (!page.frames().includes(frame)) throw new Error("Resizing reloaded the panel session");
  await assertFits();
  await handle.press("ArrowRight");
  if (Math.abs((await panel.boundingBox()).width - wider.width + 24) > 2) throw new Error("Keyboard resize failed");
  await assertFits();

  await page.setViewportSize({ width: 800, height: 720 });
  await assertFits();
  if ((await panel.boundingBox()).width > 400) throw new Error("Narrow window left no room for the video");
  await page.setViewportSize({ width: 1280, height: 720 });
  await assertFits();

  // Exercise both theater and standard layouts through YouTube's own control.
  await page.locator(".ytp-size-button").evaluate((button) => button.click());
  await assertFits();
  await page.locator(".ytp-size-button").evaluate((button) => button.click());
  await assertFits();

  await page.locator("#movie_player").evaluate((player) => player.requestFullscreen());
  await panel.waitFor({ state: "hidden" });
  if (await handle.isVisible()) throw new Error("Resize handle remains in fullscreen");
  await page.evaluate(() => document.exitFullscreen());
  await panel.waitFor({ state: "visible" });
  await assertFits();
  await frame.getByRole("button", { name: "隐藏侧栏", exact: true }).click();
  await panel.waitFor({ state: "hidden" });
  await page.waitForFunction(() => document.querySelector("#masthead-container").getBoundingClientRect().width >= innerWidth - 2);
  await page.getByRole("button", { name: "Open YouTube Digest", exact: true }).click();
  await assertFits();
  if (!page.frames().includes(frame)) throw new Error("Hide/show reloaded the panel session");
  const savedWidth = (await panel.boundingBox()).width;
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Open YouTube Digest", exact: true }).click();
  await page.waitForFunction((width) =>
    Math.abs(document.querySelector("#youtube-digest-panel").getBoundingClientRect().width - width) < 1,
    savedWidth, { timeout: 5000 });
  await assertFits();
}
