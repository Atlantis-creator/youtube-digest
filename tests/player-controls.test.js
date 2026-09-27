const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function harness() {
  const elements = [];
  const events = {};
  const sent = [];
  function element() {
    const el = {
      children: [],
      style: {
        setProperty(k, v) {
          this[k] = v;
        },
      },
      listeners: {},
      addEventListener(k, fn) {
        this.listeners[k] = fn;
      },
      removeEventListener(k) {
        delete this.listeners[k];
      },
      setAttribute(k, v) {
        this[k] = v;
      },
      setPointerCapture() {},
      appendChild(child) {
        this.children.push(child);
        child.removed = false;
      },
      remove() {
        this.removed = true;
      },
      set textContent(value) {
        this.text = value;
        this.children = [];
      },
      get textContent() {
        return this.text || "";
      },
    };
    elements.push(el);
    return el;
  }
  const player = element();
  const video = element();
  video.currentTime = 1;
  const app = element();
  const document = {
    readyState: "loading",
    fullscreenElement: null,
    body: element(),
    addEventListener(k, fn) {
      events[k] = fn;
    },
    createElement: element,
    getElementById(id) {
      return elements.find((el) => !el.removed && el.id === id);
    },
    querySelector(s) {
      return s.includes("movie_player")
        ? player
        : s === "video.html5-main-video"
          ? video
          : s === "ytd-app"
            ? app
            : null;
    },
    querySelectorAll() {
      return [];
    },
    async exitFullscreen() {
      this.fullscreenElement = null;
      events.fullscreenchange();
    },
  };
  const window = {
    innerWidth: 1280,
    addEventListener(k, fn) { events[k] = fn; },
    dispatchEvent(event) { events[event.type]?.(event); },
    location: {
      href: "https://www.youtube.com/watch?v=videoAAAAAA",
      pathname: "/watch",
    },
  };
  const context = vm.createContext({
    console,
    URL,
    Event,
    document,
    window,
    setTimeout() {},
    clearTimeout() {},
    clearInterval() {},
    chrome: {
      runtime: {
        getURL: (p) => `chrome-extension://test/${p}`,
        onMessage: {
          addListener(fn) {
            events.message = fn;
          },
        },
        sendMessage: async (m) => {
          sent.push(m);
          return {};
        },
      },
    },
  });
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../content.js"), "utf8"),
    context,
  );
  return { context, document, window, events, player, video, sent };
}

function sendSubtitles(h, mode = "original", videoId = "videoAAAAAA") {
  h.context.setVideoSubtitles({
    videoId,
    enabled: true,
    mode,
    segments: [
      {
        start: 0,
        end: 10,
        original: "English original",
        translated: "中文翻译",
      },
    ],
  });
}

test("original subtitles render without translation and can be independently disabled", () => {
  const h = harness();
  sendSubtitles(h);
  const overlay = h.document.getElementById("youtube-digest-subtitle-overlay");
  assert.equal(overlay.style.display, "block");
  assert.deepEqual(
    overlay.children.map((c) => c.textContent),
    ["English original"],
  );
  h.context.togglePlayerSubtitles();
  sendSubtitles(h, "bilingual");
  assert.equal(overlay.style.display, "none");
  h.context.togglePlayerSubtitles();
  assert.deepEqual(
    overlay.children.map((c) => c.textContent),
    ["English original", "中文翻译"],
  );
});

test("late subtitles from video A cannot overwrite video B; new video resets visibility", () => {
  const h = harness();
  sendSubtitles(h);
  h.context.togglePlayerSubtitles();
  h.window.location.href = "https://www.youtube.com/watch?v=videoBBBBBB";
  h.events["yt-navigate-finish"]();
  sendSubtitles(h);
  assert.equal(
    h.document.getElementById("youtube-digest-subtitle-overlay"),
    undefined,
  );
  sendSubtitles(h, "original", "videoBBBBBB");
  assert.equal(
    h.document.getElementById("youtube-digest-subtitle-overlay").style.display,
    "block",
  );
});

test("same-video navigation preserves subtitle-off choice", () => {
  const h = harness();
  sendSubtitles(h);
  h.context.togglePlayerSubtitles();
  h.window.location.href += "&t=10";
  h.events["yt-navigate-finish"]();
  sendSubtitles(h);
  assert.equal(
    h.document.getElementById("youtube-digest-subtitle-overlay").style.display,
    "none",
  );
});

test("fullscreen hides the same iframe and restores only a previously visible panel", async () => {
  const h = harness();
  await h.context.openDigestPanel();
  const panel = h.document.getElementById("youtube-digest-panel");
  h.document.fullscreenElement = h.player;
  h.events.fullscreenchange();
  assert.equal(panel.style.visibility, "hidden");
  await h.document.exitFullscreen();
  assert.equal(panel.style.visibility, "visible");
  h.events.message({ action: "hideDigestPanel" }, {}, () => {});
  h.document.fullscreenElement = h.player;
  h.events.fullscreenchange();
  await h.document.exitFullscreen();
  assert.equal(panel.style.visibility, "hidden");
  await h.context.openDigestPanel();
  assert.equal(h.document.getElementById("youtube-digest-panel"), panel);
});

test("hidden panel continues receiving playback updates even with subtitles off", async () => {
  const h = harness();
  await h.context.openDigestPanel();
  sendSubtitles(h);
  h.context.togglePlayerSubtitles();
  h.events.message({ action: "hideDigestPanel" }, {}, () => {});
  h.video.currentTime = 15.25;
  h.video.listeners.timeupdate();
  assert.equal(h.sent.at(-1).action, "digestPlayback");
  assert.equal(h.sent.at(-1).currentTime, 15.25);
  assert.equal(h.sent.at(-1).videoId, "videoAAAAAA");
});

test("resizing preserves the iframe and clamps width to leave room for the page", async () => {
  const h = harness();
  await h.context.openDigestPanel();
  const panel = h.document.getElementById("youtube-digest-panel");
  const handle = h.document.getElementById("youtube-digest-panel-resize");
  handle.listeners.pointerdown({button:0, pointerId:1, preventDefault() {}});
  handle.listeners.pointermove({clientX:700});
  assert.equal(panel.style.width, "580px");
  assert.equal(panel.style.pointerEvents, "none");
  handle.listeners.pointerup();
  assert.equal(panel.style.pointerEvents, "auto");
  assert.equal(h.sent.at(-1).action, "savePanelWidth");
  assert.equal(h.sent.at(-1).width, 580);
  h.context.setDigestPanelWidth(9999);
  assert.equal(panel.style.width, "800px");
  h.context.setDigestPanelWidth(1);
  assert.equal(panel.style.width, "280px");
  assert.equal(h.document.getElementById("youtube-digest-panel"), panel);
});

test("resize handle supports keyboard and disappears with hidden/fullscreen panel", async () => {
  const h = harness();
  await h.context.openDigestPanel();
  const panel = h.document.getElementById("youtube-digest-panel");
  const handle = h.document.getElementById("youtube-digest-panel-resize");
  handle.listeners.keydown({key:"ArrowLeft", preventDefault() {}});
  assert.equal(panel.style.width, "424px");
  assert.equal(handle['aria-valuenow'], '424');
  h.document.fullscreenElement = h.player;
  h.events.fullscreenchange();
  assert.equal(handle.style.display, 'none');
  assert.equal(h.document.getElementById('youtube-digest-layout').textContent, '');
  await h.document.exitFullscreen();
  assert.equal(handle.style.display, 'block');
  assert.equal(panel.style.width, "424px");
});

test("narrow windows constrain the dock without destroying the preferred width", async () => {
  const h = harness();
  await h.context.openDigestPanel();
  h.context.setDigestPanelWidth(600);
  h.window.innerWidth = 600;
  h.events.resize();
  assert.equal(h.document.getElementById('youtube-digest-panel').style.width, '300px');
  h.window.innerWidth = 1280;
  h.events.resize();
  assert.equal(h.document.getElementById('youtube-digest-panel').style.width, '600px');
});
