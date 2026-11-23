const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const listener = { addListener() {} };
const chrome = {
  scripting: {},
  tabs: { onUpdated: listener, onRemoved: listener },
  runtime: { onMessage: listener },
};
const context = vm.createContext({ chrome });
vm.runInContext(fs.readFileSync(path.join(__dirname, "../extension/background.js"), "utf8"), context);

async function readFrames(texts) {
  chrome.scripting.executeScript = async () => texts.map((text, index) => ({
    result: { text, top: index === 0, url: "https://example.test/lesson", title: "Lesson" },
  }));
  return context.readTab(42);
}

async function main() {
  const prefix = "A network connects devices and transmits data. ".repeat(30);
  const first = prefix + "Switches forward frames.";
  const second = prefix + "Routers forward packets.";
  const lesson = await readFrames([first, second, first]);
  assert(lesson.text.includes(first));
  assert(lesson.text.includes(second));
  assert.equal(lesson.text.split(first).length - 1, 1);

  const japanese = "ネットワークの教材".repeat(80);
  const chinese = "网络课程内容".repeat(120);
  const multilingual = await readFrames([japanese, chinese]);
  assert(multilingual.text.includes(japanese));
  assert(multilingual.text.includes(chinese));

  const short = "A lesson repeated in the top frame and its embedded frame.";
  const repeated = await readFrames([short, short]);
  assert.equal(repeated.text, short);

  const introduction = "This lesson introduces network switches and their role in forwarding frames.";
  const transcript = "The embedded transcript describes network traffic and switch ports. ".repeat(15);
  const withTranscript = await readFrames([introduction, transcript]);
  assert(withTranscript.text.includes(introduction), "a short top-frame lesson must not be discarded");
  assert(withTranscript.text.includes(transcript), "the embedded transcript must remain readable");

  chrome.scripting.executeScript = async () => [
    { result: { top: true, url: "https://example.test/lesson", title: "Lesson", text: "Menu" } },
    { result: { top: false, url: "https://example.test/first", title: "First", text: introduction } },
    { result: { top: false, url: "https://example.test/second", title: "Second", text: transcript } },
  ];
  const embedded = await context.readTab(42);
  assert(embedded.text.includes(introduction), "a readable frame must not be mistaken for the top frame");
  assert(embedded.text.includes(transcript));
  assert.equal(embedded.url, "https://example.test/lesson", "the followed tab must supply the page URL");
  assert.equal(embedded.title, "Lesson", "the followed tab must supply the page title");

  chrome.scripting.executeScript = async () => [
    { result: { top: true, url: "https://example.test/empty", title: "Empty shell", text: "" } },
    { result: { top: false, url: "https://example.test/transcript", title: "Transcript", text: transcript } },
  ];
  const emptyShell = await context.readTab(42);
  assert.equal(emptyShell.url, "https://example.test/empty");
  assert.equal(emptyShell.title, "Empty shell");
  assert.equal(emptyShell.text, transcript);

  chrome.scripting.executeScript = async () => [
    { result: null },
    { result: { top: false, url: "https://example.test/transcript", title: "Transcript", text: transcript } },
  ];
  const withoutTop = await context.readTab(42);
  assert.equal(withoutTop.url, "https://example.test/transcript");
  assert.equal(withoutTop.title, "Transcript");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
