// Study Buddy Page Reader — background service worker.
// Follows ONE tab you choose, reads its text (all frames), and sends it to Study Buddy on your PC.
const SERVER = "http://127.0.0.1:8765";
const HEADERS = { "Content-Type": "application/json", "X-Study-Buddy": "1" };

const session = {
  get: (k) => chrome.storage.session.get(k),
  set: (o) => chrome.storage.session.set(o),
};
const local = {
  get: (k) => chrome.storage.local.get(k),
  set: (o) => chrome.storage.local.set(o),
};

// ---------- runs inside the page (every frame) ----------
// Turns the page into clean, structured text: headings (## / ###), paragraphs, "- " list items and
// "a | b" table rows, in reading order. Skips menus, player controls, hidden bits and scripts.
function sbExtract() {
  const host = location.hostname;
  const JUNK_HOST = /(^|\.)(google\.com|gstatic\.com|recaptcha\.net|doubleclick\.net|googlesyndication\.com|youtube\.com|vimeo\.com|hotjar\.com|intercom\.io|zendesk\.com|pendo\.io)$/;
  if (JUNK_HOST.test(host) || /recaptcha/i.test(location.href) || !document.body) return null;

  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "CANVAS", "BUTTON", "SELECT", "OPTION",
                        "TEXTAREA", "AUDIO", "VIDEO", "IFRAME", "OBJECT", "EMBED", "NAV", "FOOTER", "DIALOG", "IMG"]);
  const SKIP_ROLES = /^(navigation|menu|menubar|toolbar|banner|contentinfo|search|dialog|alertdialog|tooltip|slider|progressbar|tablist)$/;
  const blocks = [];
  const style = (el) => { try { return getComputedStyle(el); } catch (e) { return null; } };
  const clean = (t) => (t || "").replace(/[ \t ]+/g, " ").replace(/\n\s*\n+/g, "\n").trim();

  function skip(el) {
    if (SKIP.has(el.tagName)) return true;
    const role = el.getAttribute("role");
    if (role && SKIP_ROLES.test(role)) return true;
    if (el.getAttribute("aria-hidden") === "true" || el.hidden) return true;
    if (el.checkVisibility && !el.closest("details") && !el.checkVisibility({ visibilityProperty: true })) return true;
    return false;
  }
  function isBlock(el) {
    const d = style(el)?.display || "block";
    return !(d === "inline" || d === "inline-block" || d === "inline-flex" || d === "inline-grid" || d === "none");
  }
  function looksLikeHeading(el, text) {
    if (text.length > 90 || text.includes("\n") || /[.;:!?,]$/.test(text) || text.split(" ").length > 12) return false;
    const st = style(el);
    const bold = st && (parseInt(st.fontWeight, 10) >= 600) && parseFloat(st.fontSize) >= 14;
    const big = st && parseFloat(st.fontSize) >= 18;
    return bold || big || /(^|[-_ ])(head|heading|title|subtitle)([-_ ]|$)/i.test(el.className || "");
  }
  function push(kind, text) { text = clean(text); if (text) blocks.push({ kind, text }); }

  function visit(el) {
    if (skip(el)) return;
    const tag = el.tagName;
    if (/^H[1-6]$/.test(tag)) return push(tag <= "H2" ? "h2" : "h3", el.innerText);
    if (tag === "LI") return push("li", el.innerText.replace(/\n+/g, " "));
    if (tag === "PRE") return push("pre", el.innerText);
    if (tag === "TABLE") {
      for (const tr of el.querySelectorAll("tr")) {
        const cells = [...tr.children].map((c) => clean(c.innerText).replace(/\n/g, " "));
        if (cells.some(Boolean)) push("tr", cells.join(" | "));
      }
      return;
    }
    let hasBlockChild = false;
    for (const c of el.children) { if (!skip(c) && isBlock(c)) { hasBlockChild = true; break; } }
    if (!hasBlockChild) {
      const t = clean(el.innerText);
      if (t) push(looksLikeHeading(el, t) ? "h3" : "p", t);
      return;
    }
    let inline = "";
    const flush = () => { if (inline.trim()) push("p", inline); inline = ""; };
    for (const n of el.childNodes) {
      if (n.nodeType === 3) inline += n.textContent;
      else if (n.nodeType === 1) {
        if (skip(n)) continue;
        if (isBlock(n)) { flush(); visit(n); } else inline += n.innerText || "";
      }
    }
    flush();
  }
  visit(document.body);

  // Checked answers aren't in the text — note them for quizzes/labs.
  document.querySelectorAll("input:checked").forEach((i) => {
    const label = i.labels?.[0]?.innerText || i.closest("label")?.innerText || i.value;
    if (label) push("p", `(selected) ${label.trim().slice(0, 200)}`);
  });

  // Section number + title, e.g. "1.1.1" followed by "Networking Concepts", or "1.1.1 Networking Concepts"
  let section = "", sectionTitle = "";
  for (let k = 0; k < blocks.length && !section; k++) {
    const t = blocks[k].text;
    let m = t.match(/^(\d{1,2}(?:\.\d{1,2}){1,3})$/);
    if (m && blocks[k + 1] && blocks[k + 1].text.length < 90) { section = m[1]; sectionTitle = blocks[k + 1].text; break; }
    m = t.match(/^(\d{1,2}(?:\.\d{1,2}){1,3})\s+([A-Za-z].{2,80})$/);
    if (m && !/[.!?]$/.test(t)) { section = m[1]; sectionTitle = m[2]; }
  }

  const lines = [];
  for (const b of blocks) {
    if (b.kind === "h2") lines.push("", "## " + b.text.replace(/\n/g, " "), "");
    else if (b.kind === "h3") lines.push("", "### " + b.text, "");
    else if (b.kind === "li") lines.push("- " + b.text);
    else if (b.kind === "tr") lines.push(b.text);
    else lines.push(b.text, "");
  }
  const text = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  // Encoded blobs (tracking/captcha data) have almost no spaces — not lesson text.
  const words = text.split(/\s+/).length;
  if (text.length > 2000 && text.length / Math.max(1, words) > 25) return null;
  return {
    url: location.href, title: document.title, top: window === window.top, text: text.slice(0, 150000),
    section, sectionTitle, selection: String(window.getSelection?.() || "").slice(0, 4000),
  };
}

function sbObserve() {
  if (window.__sbObserving) return;
  window.__sbObserving = true;
  let t;
  const ping = () => {
    clearTimeout(t);
    t = setTimeout(() => { try { chrome.runtime.sendMessage({ type: "sb-changed" }); } catch (e) {} }, 1200);
  };
  new MutationObserver(ping).observe(document.documentElement, { subtree: true, childList: true, characterData: true });
  document.addEventListener("selectionchange", ping);
  addEventListener("hashchange", ping);
  addEventListener("popstate", ping);
  document.addEventListener("change", ping, true);
  // A server restart clears its in-memory page. Re-send the followed tab even if its DOM is idle.
  if (window === window.top) setInterval(() => {
    try { chrome.runtime.sendMessage({ type: "sb-heartbeat" }); } catch (e) {}
  }, 60_000);
}

// ---------- background logic ----------
let pushTimer = null, saveTimer = null, lastHash = "";

function hash(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return String(h); }

async function readTab(tabId) {
  const results = await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: sbExtract });
  const frames = results.map((r) => r.result).filter((r) => r && r.text && r.text.trim().length > 40);
  if (!frames.length) throw new Error("No readable text on this page (PDF viewer, video only, or a browser page).");
  const top = frames.find((f) => f.top) || frames[0];
  // Lesson content usually lives in an embedded frame; the top frame is mostly the platform's menus.
  // Order: frames with the most text first, and drop exact duplicates (the same frame can load twice).
  const seen = new Set(), parts = [];
  for (const f of [...frames].sort((a, b) => b.text.length - a.text.length)) {
    const key = f.text.replace(/\W+/g, "").slice(0, 600);
    if (seen.has(key)) continue;
    seen.add(key);
    if (f === top && frames.length > 1 && f.text.length < 600) continue; // top frame is just menus
    parts.push(f.text);
  }
  const withSection = frames.find((f) => f.section) || {};
  return { url: top.url, title: top.title || "Untitled page", text: parts.join("\n\n"),
           section: withSection.section || "", section_title: withSection.sectionTitle || "",
           selection: frames.map((f) => f.selection).find((s) => s && s.trim()) || "" };
}

async function badge(tabId, text, color) {
  try { await chrome.action.setBadgeText({ tabId, text }); if (color) await chrome.action.setBadgeBackgroundColor({ tabId, color }); } catch (e) {}
}

async function push(tabId, { save = false, force = false } = {}) {
  let data;
  try { data = await readTab(tabId); }
  catch (e) { await session.set({ lastPush: { ok: false, error: e.message, at: Date.now() } }); await badge(tabId, "!", "#c9473d"); return; }
  const h = hash(data.url + data.title + data.text + data.selection);
  const changed = h !== lastHash;
  if (!changed && !save && !force) return;
  const { autosave = false, course = "" } = await local.get(["autosave", "course"]);
  try {
    const r = await fetch(`${SERVER}/api/page`, { method: "POST", headers: HEADERS,
      body: JSON.stringify({ ...data, save, course: course || null }) });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    lastHash = h;
    await session.set({ lastPush: { ok: true, title: body.title || data.title, chars: data.text.length,
      at: Date.now(), saved: body.saved || null, activity: !!body.activity } });
    await badge(tabId, "ON", "#2e9d62");
    if (changed) clearTimeout(saveTimer);
    if (autosave && changed && !save && !body.activity && data.text.length > 800) { // save settled lessons, not labs
      saveTimer = setTimeout(() => push(tabId, { save: true }), 8000);
    }
    return body;
  } catch (e) {
    await session.set({ lastPush: { ok: false, error: `Study Buddy isn't reachable (${e.message}). Is run.bat running?`, at: Date.now() } });
    await badge(tabId, "!", "#c9473d");
  }
}

function schedulePush(tabId, delay = 700, force = false) {
  clearTimeout(pushTimer);
  pushTimer = setTimeout(() => push(tabId, { force }), delay);
}

async function startFollowing(tabId) {
  await session.set({ followTabId: tabId }); lastHash = "";
  try { await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: sbObserve }); } catch (e) {}
  return push(tabId, { force: true });
}

async function stopFollowing() {
  const { followTabId } = await session.get("followTabId");
  if (followTabId != null) await badge(followTabId, "", null);
  await session.set({ followTabId: null, lastPush: null }); lastHash = "";
  try { await fetch(`${SERVER}/api/page`, { method: "DELETE", headers: HEADERS }); } catch (e) {}
}

chrome.tabs.onUpdated.addListener(async (tabId, info) => {
  const { followTabId } = await session.get("followTabId");
  if (tabId !== followTabId) return;
  if (info.status === "complete") {
    try { await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: sbObserve }); } catch (e) {}
    schedulePush(tabId, 600);
  } else if (info.url) schedulePush(tabId, 1200);
});
chrome.tabs.onRemoved.addListener(async (tabId) => {
  const { followTabId } = await session.get("followTabId");
  if (tabId === followTabId) stopFollowing();
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    const { followTabId } = await session.get("followTabId");
    switch (msg.type) {
      case "sb-changed":
        if (sender.tab && sender.tab.id === followTabId) schedulePush(followTabId);
        return reply({});
      case "sb-heartbeat":
        if (sender.tab && sender.tab.id === followTabId) schedulePush(followTabId, 0, true);
        return reply({});
      case "status": {
        const { lastPush } = await session.get("lastPush");
        const settings = await local.get(["autosave", "course"]);
        let server = { ok: false, courses: [], active: null };
        try {
          const [cs, pg] = await Promise.all([fetch(`${SERVER}/api/courses`).then((r) => r.json()), fetch(`${SERVER}/api/page`).then((r) => r.json())]);
          server = { ok: true, courses: cs, active: pg.course };
        } catch (e) {}
        return reply({ followTabId, lastPush, server, autosave: !!settings.autosave, course: settings.course || "" });
      }
      case "follow":
        if (msg.on) await startFollowing(msg.tabId); else await stopFollowing();
        return reply({ ok: true });
      case "sendNow":
        return reply(await push(msg.tabId, { force: true }) || {});
      case "saveNow":
        return reply(await push(msg.tabId, { save: true, force: true }) || {});
      case "settings":
        await local.set({ autosave: !!msg.autosave, course: msg.course || "" });
        return reply({ ok: true });
    }
    reply({});
  })();
  return true; // async reply
});
