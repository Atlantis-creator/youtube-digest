// Playwright CLI run-code --filename tests/browser/follow-playback.js
// Requires this repository's sidepanel.html opened from disk (file://).
// Stubs the extension APIs, plays a long transcript, seeks five minutes ahead
// and asserts the reader is never dropped out of follow mode without touching
// the transcript. Then a real wheel scroll must still drop follow mode.
async (page) => {
  if (!page.url().endsWith("/sidepanel.html")) {
    throw new Error("Open sidepanel.html from this repository before running");
  }
  await page.setViewportSize({ width: 320, height: 760 });
  await page.addInitScript(() => {
    const startedAt = Date.now();
    window.__clock = { offset: 0 };
    window.chrome = {
      storage: { local: { get: async () => ({}), set: async () => {}, remove: async () => {} } },
      tabs: { onUpdated: { addListener() {} } },
      runtime: {
        onMessage: { addListener() {} },
        sendMessage: async (message) => {
          if (message.payload?.action !== "getCurrentTime") return {};
          const currentTime = window.__clock.offset + (Date.now() - startedAt) / 1000;
          return { success: true, response: { currentTime } };
        },
      },
    };
  });
  await page.reload();

  await page.evaluate(() => {
    const words = "you could get an image of a smoke trail render one in fusion".split(" ");
    const captions = Array.from({ length: 1200 }, (_, index) => ({
      text: `${Array.from({ length: 10 }, (__, n) => words[(index * 7 + n) % words.length]).join(" ")}${index % 3 ? "" : "."}`,
      start: index * 3,
      duration: 3,
    }));
    youtubeTabId = 1;
    currentVideoId = "follow-playback";
    currentTranscript = captions;
    showState("results");
    switchTab("transcript");
    renderTranscript();
  });

  const followButton = page.locator("#followPlaybackBtn");
  const assertStillFollowing = async (label) => {
    if (await followButton.isVisible()) throw new Error(`Follow playback appeared ${label}`);
  };

  await page.waitForTimeout(3000);
  await assertStillFollowing("during steady playback");
  // A long seek makes the smooth scroll outlast any fixed grace window.
  await page.evaluate(() => { window.__clock.offset += 300; });
  for (let i = 0; i < 8; i++) {
    await page.waitForTimeout(500);
    await assertStillFollowing("after a five-minute seek without user input");
  }

  await page.locator("#contentArea").hover();
  await page.mouse.wheel(0, -400);
  await followButton.waitFor({ state: "visible", timeout: 2000 })
    .catch(() => { throw new Error("Wheel scrolling did not leave follow mode"); });

  await followButton.click();
  await followButton.waitFor({ state: "hidden" });
  await page.keyboard.press("PageUp");
  await followButton.waitFor({ state: "visible", timeout: 2000 })
    .catch(() => { throw new Error("Keyboard scrolling did not leave follow mode"); });
}
