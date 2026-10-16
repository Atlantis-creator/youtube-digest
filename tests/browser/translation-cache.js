// Playwright CLI run-code --filename tests/browser/translation-cache.js
// Requires this repository's sidepanel.html opened from disk (file://).
// Switches the sidebar from bilingual to Chinese while the first translation
// batch is in flight. Translations do not depend on the sidebar mode, so no
// segment may be sent to the provider twice, and the late result must land.
async (page) => {
  if (!page.url().endsWith("/sidepanel.html")) {
    throw new Error("Open sidepanel.html from this repository before running");
  }
  await page.setViewportSize({ width: 320, height: 760 });
  await page.addInitScript(() => {
    window.__translated = [];
    window.chrome = {
      storage: { local: { get: async () => ({}), set: async () => {}, remove: async () => {} } },
      tabs: { onUpdated: { addListener() {} } },
      runtime: {
        onMessage: { addListener() {} },
        sendMessage: async (message) => {
          if (message.payload?.action === "getCurrentTime") {
            return { success: true, response: { currentTime: 1 } };
          }
          if (message.action !== "translateContent") return {};
          const { segments } = message.content;
          window.__translated.push(...segments.map(({ id }) => id));
          await new Promise((resolve) => setTimeout(resolve, 1500));
          return {
            success: true,
            translatedContent: { segments: segments.map(({ id }) => ({ id, text: "译文" })) },
          };
        },
      },
    };
  });
  await page.reload();

  await page.evaluate(() => {
    youtubeTabId = 1;
    currentVideoId = "translation-cache";
    currentTranscript = Array.from({ length: 60 }, (_, index) => ({
      text: `sentence number ${index} goes here.`,
      start: index * 3,
      duration: 3,
    }));
    currentTranscriptMode = "bilingual";
    showState("results");
    switchTab("transcript");
    refreshTranscriptView();
  });
  await page.waitForTimeout(500);
  await page.evaluate(() => handleTranscriptModeChange("zh"));
  await page.waitForTimeout(6000);

  const translated = await page.evaluate(() => window.__translated);
  const twice = translated.filter((id, index) => translated.indexOf(id) !== index);
  if (twice.length) throw new Error(`Translated twice after a mode switch: ${twice.join(", ")}`);
  const firstRow = await page.locator(".transcript-entry").first().getAttribute("class");
  if (!firstRow.includes("translated")) throw new Error("The in-flight translation was dropped");
}
