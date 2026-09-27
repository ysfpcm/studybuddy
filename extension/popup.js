const $ = (s) => document.querySelector(s);
const msg = (m) => chrome.runtime.sendMessage(m);
let tab;

function ago(t) { const s = Math.round((Date.now() - t) / 1000); return s < 60 ? `${s}s ago` : `${Math.round(s / 60)} min ago`; }

async function refresh() {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const st = await msg({ type: "status" });
  $("#dot").classList.toggle("ok", st.server.ok);
  $("#server").textContent = st.server.ok ? "connected to your tutor" : "Study Buddy not running — start run.bat";
  const following = st.followTabId === tab.id;
  const elsewhere = st.followTabId != null && !following;
  $("#follow").textContent = following ? "✓ Following this tab (click to stop)" : elsewhere ? "Follow this tab instead" : "Follow this tab";
  $("#follow").className = following ? "on" : "primary";
  $("#followHint").textContent = elsewhere ? "You're following a different tab right now." : following
    ? "Reading along. Scroll, click Next, open sections — it updates automatically."
    : "Your tutor will read this page's text live as you study — and only this tab.";
  $("#send").disabled = $("#save").disabled = !following || !st.server.ok;
  const cur = $("#course").value || st.course;
  $("#course").innerHTML = `<option value="">Course: the one open in Study Buddy${st.server.active ? "" : " (none open)"}</option>` +
    st.server.courses.map((c) => `<option value="${c.slug}">${c.code ? c.code + " · " : ""}${c.name}</option>`).join("");
  $("#course").value = cur;
  $("#autosave").checked = st.autosave;
  const lp = st.lastPush;
  if (following && lp?.activity) $("#save").disabled = true;
  $("#last").hidden = !following || !lp;
  if (lp) {
    $("#lastTitle").textContent = lp.ok ? lp.title : "Couldn't sync";
    $("#lastInfo").textContent = lp.ok ? `${lp.chars.toLocaleString()} characters · ${ago(lp.at)}${lp.activity ? " · lab/activity: synced, no lesson note" : lp.saved ? " · saved to notes" : ""}` : ago(lp.at);
    $("#lastErr").textContent = lp.ok ? "" : lp.error;
  }
}

$("#follow").onclick = async () => {
  const st = await msg({ type: "status" });
  await msg({ type: "follow", tabId: tab.id, on: st.followTabId !== tab.id });
  refresh();
};
$("#send").onclick = async () => { await msg({ type: "sendNow", tabId: tab.id }); refresh(); };
$("#save").onclick = async () => { await saveSettings(); await msg({ type: "saveNow", tabId: tab.id }); refresh(); };
async function saveSettings() { await msg({ type: "settings", autosave: $("#autosave").checked, course: $("#course").value }); }
$("#autosave").onchange = saveSettings;
$("#course").onchange = saveSettings;
refresh(); setInterval(refresh, 2000);
