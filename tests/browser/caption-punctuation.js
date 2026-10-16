// Playwright CLI run-code --filename tests/browser/caption-punctuation.js
// Requires this repository's sidepanel.html opened from disk (file://).
// Opens unpunctuated auto-captions in bilingual mode. Rows must show the
// "正在断句…" hint and stay untranslated until DeepSeek's punctuation for the
// chunk being played returns; then they regroup into sentences and translate.
async (page) => {
  if (!page.url().endsWith("/sidepanel.html")) {
    throw new Error("Open sidepanel.html from this repository before running");
  }
  await page.setViewportSize({ width: 320, height: 760 });
  await page.addInitScript(() => {
    window.__punctuated = [];
    window.__translated = [];
    window.chrome = {
      storage: { local: { get: async () => ({}), set: async () => {}, remove: async () => {} } },
      tabs: { onUpdated: { addListener() {} } },
      runtime: {
        onMessage: { addListener() {} },
        sendMessage: async (message) => {
          if (message.payload?.action === "getCurrentTime") {
            return { success: true, response: { currentTime: 10 } };
          }
          if (message.action === "punctuateCaptions") {
            window.__punctuated.push(message.text.split(" ")[0]);
            await new Promise((resolve) => setTimeout(resolve, 1500));
            const words = message.text.split(" ");
            const text = words.map((word, index) => (index % 8 === 7 ? `${word}.` : word)).join(" ");
            return { success: true, text };
          }
          if (message.action === "translateContent") {
            window.__translated.push(...message.content.segments.map(({ text }) => text));
            return {
              success: true,
              translatedContent: { segments: message.content.segments.map(({ id }) => ({ id, text: "译文" })) },
            };
          }
          return {};
        },
      },
    };
  });
  await page.reload();

  await page.evaluate(() => {
    youtubeTabId = 1;
    currentVideoId = "caption-punctuation";
    currentTranscript = Array.from({ length: 200 }, (_, index) => ({
      text: `word${index} spoken without any marks`,
      start: index * 3,
      duration: 3,
    }));
    currentTranscriptMode = "bilingual";
    showState("results");
    switchTab("transcript");
    refreshTranscriptView();
  });

  const hint = page.locator(".transcript-pending-hint").first();
  await hint.waitFor({ state: "visible", timeout: 2000 });
  await page.waitForTimeout(800);
  if ((await page.evaluate(() => window.__translated)).length) {
    throw new Error("Rows waiting for punctuation were sent for translation");
  }

  await page.waitForFunction(() => window.__translated.length > 0, null, { timeout: 5000 })
    .catch(() => { throw new Error("Punctuated rows were never translated"); });
  const state = await page.evaluate(() => ({
    punctuated: window.__punctuated,
    firstRow: document.querySelector(".transcript-entry .transcript-original")?.textContent,
    firstHasHint: !!document.querySelector(".transcript-entry")?.querySelector(".transcript-pending-hint"),
    translated: window.__translated,
  }));
  if (state.punctuated[0] !== "word0") throw new Error("The chunk being played was not punctuated first");
  if (state.firstHasHint || !/\.$/.test(state.firstRow || "")) {
    throw new Error(`First row did not become a sentence: ${state.firstRow}`);
  }
  if (!state.translated.every((text) => /\.$/.test(text))) {
    throw new Error("A translation request carried unpunctuated slices");
  }
}
