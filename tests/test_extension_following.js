const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function createHarness({ readGate = null, postGate = null } = {}) {
  const stored = {};
  const timers = new Map();
  const reads = [];
  const requests = [];
  let timerId = 0;
  const listener = { addListener() {} };
  const chrome = {
    storage: {
      session: {
        get: async () => ({ ...stored }),
        set: async (values) => Object.assign(stored, values),
      },
      local: { get: async () => ({ autosave: true }), set: async () => {} },
    },
    scripting: {
      executeScript: async ({ target, func }) => {
        if (func.name === "sbObserve") return [];
        reads.push(target.tabId);
        if (readGate) await readGate;
        return [{ result: { top: true, url: `https://example.test/${target.tabId}`,
          title: `Tab ${target.tabId}`, text: "Lesson text ".repeat(100) } }];
      },
    },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {} },
    tabs: { onUpdated: listener, onRemoved: listener },
    runtime: { onMessage: listener },
  };
  const context = vm.createContext({
    chrome,
    fetch: async (url, options) => {
      requests.push({ method: options.method, body: options.body && JSON.parse(options.body) });
      if (options.method === "POST" && postGate) await postGate;
      return { ok: true, json: async () => ({}) };
    },
    setTimeout: (callback) => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: (id) => timers.delete(id),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../extension/background.js"), "utf8"), context);
  return { context, reads, requests, stored, timers };
}

async function runTimers(timers) {
  const pending = [...timers.values()];
  timers.clear();
  for (const callback of pending) await callback();
}

async function main() {
  const stopped = createHarness();
  await stopped.context.startFollowing(1);
  stopped.context.schedulePush(1);
  await stopped.context.stopFollowing();
  await runTimers(stopped.timers);
  assert.deepEqual(stopped.reads, [1], "stopping must cancel queued reads and autosaves");
  assert.deepEqual(stopped.requests.map((request) => request.method), ["POST", "DELETE"]);

  const switched = createHarness();
  await switched.context.startFollowing(1);
  switched.context.schedulePush(1);
  await switched.context.startFollowing(2);
  await runTimers(switched.timers);
  assert.deepEqual(switched.reads, [1, 2, 2], "switching must only keep the new tab's autosave");
  assert.deepEqual(switched.requests.map((request) => request.body.url), [
    "https://example.test/1", "https://example.test/2", "https://example.test/2",
  ]);
  assert.equal(switched.requests[2].body.save, true);

  let finishRead;
  const readGate = new Promise((resolve) => { finishRead = resolve; });
  const interrupted = createHarness({ readGate });
  const starting = interrupted.context.startFollowing(1);
  while (!interrupted.reads.length) await new Promise((resolve) => setImmediate(resolve));
  await interrupted.context.stopFollowing();
  finishRead();
  await starting;
  await runTimers(interrupted.timers);
  assert.deepEqual(interrupted.requests.map((request) => request.method), ["DELETE"],
    "a read finishing after stopping must not sync or schedule an autosave");

  let finishOldRead;
  const oldReadGate = new Promise((resolve) => { finishOldRead = resolve; });
  const changing = createHarness({ readGate: oldReadGate });
  const oldTab = changing.context.startFollowing(1);
  while (!changing.reads.length) await new Promise((resolve) => setImmediate(resolve));
  const newTab = changing.context.startFollowing(2);
  while (changing.reads.length < 2) await new Promise((resolve) => setImmediate(resolve));
  finishOldRead();
  await Promise.all([oldTab, newTab]);
  await runTimers(changing.timers);
  assert.deepEqual(changing.requests.map((request) => request.body.url), [
    "https://example.test/2", "https://example.test/2",
  ], "a read from the previous tab must not sync or schedule an autosave");

  let finishPost;
  const postGate = new Promise((resolve) => { finishPost = resolve; });
  const posting = createHarness({ postGate });
  const startPosting = posting.context.startFollowing(1);
  while (!posting.requests.length) await new Promise((resolve) => setImmediate(resolve));
  await posting.context.stopFollowing();
  finishPost();
  await startPosting;
  await runTimers(posting.timers);
  assert.deepEqual(posting.requests.map((request) => request.method), ["POST", "DELETE"]);
  assert.equal(posting.stored.lastPush, null, "an old response must not restore sync status");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
