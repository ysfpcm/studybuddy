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
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
