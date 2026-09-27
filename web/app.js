// Study Buddy front end.
// Channels: "live" = GPT-Live-1 premium voice (WebRTC) · "economy" = browser recognition + Luna + mini TTS · "text".
const eid = (p) => `${p}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;

const state = {
  course: null, channel: "live", cfg: {},
  active: false, sid: null, chatId: null, startedAt: 0, timer: null, lastActivity: 0, idleWarned: false,
  transcript: [], lastRole: null, lastBubble: null,
  // live
  pc: null, dc: null, mic: null, muted: false, pendingCalls: [], delegationMode: "responses",
  userSinceDelegation: "", closedResolve: null, rawUsage: null, clientUsage: { input_tokens: 0, output_tokens: 0, input_tokens_details: { cached_tokens: 0 } }, seenResponses: new Set(),
  lastEndedSid: null,
  // economy
  rec: null, listening: false, busy: false, speaking: false, heard: "", sendTimer: null, ttsAbort: null, ttsAudio: null,
  // eyes
  screen: null, video: null, lastLook: null,
};

// ---------- transcript & board ----------
function bubble(role, text = "") {
  const hint = $("#transcript .hint"); if (hint) hint.remove();
  const el = document.createElement("div");
  el.className = `msg ${role}`; el.textContent = text;
  $("#transcript").appendChild(el);
  el.scrollIntoView({ block: "end" });
  return el;
}
function say(role, delta) {
  if (state.lastRole !== role || !state.lastBubble) {
    state.lastBubble = bubble(role); state.lastRole = role;
    state.transcript.push({ role, text: "", at: new Date().toISOString() });
  }
  state.lastBubble.textContent += delta;
  state.transcript[state.transcript.length - 1].text += delta;
  state.lastBubble.scrollIntoView({ block: "end" });
}
function logTurn(role, text) { state.transcript.push({ role, text, at: new Date().toISOString() }); }
function note(text, cls = "sys") {
  if ($("#chatView").hidden) return toast(text, cls); // on the course home, notes float as a toast
  const el = bubble(cls, text); state.lastRole = null; return el;
}
function toast(text, cls = "sys") {
  const t = document.createElement("div"); t.className = `toast ${cls}`; t.textContent = text;
  document.body.appendChild(t); setTimeout(() => t.remove(), cls === "err" ? 9000 : 5000);
  return t;
}

state.boards = [];
function clearBoard() {
  state.boards = [];
  $("#board").innerHTML = "Diagrams, code, math and tables the tutor puts up stay here for the chat."; $("#board").className = "muted small";
}
function showBoard({ title, markdown }, record = true) {
  if (record) state.boards.push({ title, markdown });
  const board = $("#board");
  if (board.classList.contains("muted")) { board.innerHTML = ""; board.classList.remove("muted", "small"); }
  const card = document.createElement("div"); card.className = "card";
  const h = document.createElement("h3"); h.textContent = title || "Board";
  const body = document.createElement("div"); body.className = "md";
  card.append(h, body); board.prepend(card);
  renderMd(body, markdown);
}
function showReceipt(r) {
  const el = bubble("receipt");
  const mins = r.voice_seconds / 60;
  const channelName = { live: "Premium voice", economy: "Economy voice", text: "Text" }[r.channel] || r.channel;
  const brainLine = r.brain_reported
    ? `${money(r.cost_brain)} <span class="muted">(${(r.in_tokens / 1000).toFixed(1)}k in, ${Math.round(100 * r.cached_tokens / Math.max(1, r.in_tokens))}% cached · ${(r.out_tokens / 1000).toFixed(1)}k out)</span>`
    : `<span class="muted">not reported by the API — usually a few cents/hour</span>`;
  el.innerHTML = `
    <div class="receipt-head"><strong>Session receipt</strong><span class="muted">${channelName} · ${r.mode}</span></div>
    ${r.channel === "live" ? `<div class="line"><span>Voice (${mins.toFixed(1)} min)</span><span>${money(r.cost_voice)}</span></div>` : ""}
    ${r.tts_seconds ? `<div class="line"><span>Mini TTS (~${(r.tts_seconds / 60).toFixed(1)} min spoken, estimated)</span><span>~${money(r.tts_cost)}</span></div>` : ""}
    <div class="line"><span>Luna (brain)</span><span>${brainLine}</span></div>
    ${r.vision_calls ? `<div class="line"><span>Eyes &amp; screenshots (${r.vision_calls})</span><span>${money(r.vision_cost)}</span></div>` : ""}
    <div class="line total"><span>Total</span><span>${money(r.cost_total)}</span></div>
    <div class="muted small">This month: ${money(r.month.spent)} of ${money(r.month.budget)} (${r.month.pct}%) · today ${money(r.month.today)}</div>`;
  state.lastRole = null;
}

// ---------- sidebar ----------
async function loadStatus() {
  const s = await api("/api/status"); state.cfg = s;
  $("#status").textContent = `${s.live_model} + ${s.brain_model}` + (s.api_key_set ? "" : " · ⚠ no API key in .env");
  $("#mode").innerHTML = Object.entries(s.modes).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
}
async function loadCourses() {
  const list = await api("/api/courses"); state.courses = list;
  const ul = $("#courses"); ul.innerHTML = "";
  if (!list.length) ul.innerHTML = `<li class="muted small">No course folders yet. Add one under <code>courses/</code>.</li>`;
  for (const c of list) {
    const li = document.createElement("li");
    const m = Math.round(c.avg_mastery * 100);
    li.innerHTML = `<div class="code">${esc(c.code)}</div><div class="name">${esc(c.name)}</div>
      <div class="meta">${esc(c.instructor || "")}${c.instructor ? " · " : ""}${c.concepts ? m + "% mastery" : c.files + (c.files === 1 ? " file" : " files")}</div>
      <div class="bar"><span style="width:${Math.max(2, m)}%;background:${color(c.avg_mastery)}"></span></div>`;
    li.onclick = () => selectCourse(c.slug);
    if (c.slug === state.course) li.classList.add("on");
    li.dataset.slug = c.slug; ul.appendChild(li);
  }
  let saved = "";
  try { saved = localStorage.getItem("courseSlug") || ""; } catch {}
  const keep = list.find((c) => c.slug === state.course) || list.find((c) => c.slug === saved) || list[0];
  if (keep && keep.slug !== state.course) selectCourse(keep.slug);
  else if (keep) renderCourseHeader(keep);
}
function renderCourseHeader(c) {
  $("#courseCode").textContent = [c.code, c.instructor, c.term].filter(Boolean).join(" · ");
  $("#courseTitle").textContent = c.name;
  $("#courseStats").textContent = `${c.files} file${c.files === 1 ? "" : "s"} · ${c.concepts} concepts`;
}
function selectCourse(slug) {
  if (state.active) return note("End the current session before switching courses.");
  state.course = slug; state.chatId = null; state.lastEndedSid = null;
  try { localStorage.setItem("courseSlug", slug); } catch {}
  document.querySelectorAll("#courses li").forEach((li) => li.classList.toggle("on", li.dataset.slug === slug));
  const c = (state.courses || []).find((x) => x.slug === slug); if (c) renderCourseHeader(c);
  loadProgress(); loadChats(); showHome(); setUI(); clearBoard();
  post("/api/ui/state", { course: slug }).catch(() => {});
  emit("sb:course", { slug });
}

// ---------- views: course home (chat list) <-> a chat ----------
function showHome() {
  if (state.active) return;
  state.viewingSid = null;
  $("#home").hidden = false; $("#chatView").hidden = true;
}
function showChat(title, pastSid = null) {
  state.viewingSid = pastSid;
  $("#home").hidden = true; $("#chatView").hidden = false;
  $("#chatTitle").textContent = title || "";
  $("#continueChat").hidden = !pastSid;
  $("#backHome").hidden = state.active;
}
const when = (iso) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const CH = { live: "Premium voice", economy: "Economy voice", text: "Text" };
async function loadChats() {
  if (!state.course) return;
  const course = state.course;
  const list = await api(`/api/courses/${course}/sessions`);
  if (course !== state.course) return;
  const box = $("#chatList");
  if (!list.length) {
    const c = (state.courses || []).find((x) => x.slug === state.course) || {};
    box.innerHTML = `<div class="empty">No chats yet for this course. Pick a mode and hit <b>Start session</b>, or just type below.<br><br>
      Add class files to <code>courses\\${esc(state.course)}\\material</code> and click <b>Re-index</b> so the tutor can use them${c.files ? "" : " (none yet)"}.</div>`;
    return;
  }
  box.innerHTML = "";
  for (const s of list) {
    const row = document.createElement("div"); row.className = "chat-row";
    const b = document.createElement("button"); b.className = "chat-card";
    b.innerHTML = `<span class="t">${esc(s.title)}</span><span class="c">${money(s.cost_total)}</span>
      <span class="m">${when(s.started_at)} · ${esc(CH[s.channel] || s.channel)} · ${esc((state.cfg.modes || {})[s.mode] || s.mode)}</span><span class="c">${s.turns} msgs</span>`;
    b.onclick = () => openChat(s);
    const del = document.createElement("button"); del.className = "chat-del"; del.title = "Delete chat";
    del.setAttribute("aria-label", `Delete chat: ${s.title}`); del.textContent = "🗑";
    del.onclick = async (e) => {
      e.stopPropagation();
      if (!del.classList.contains("confirm")) {   // two-click confirm, no blocking dialog
        del.classList.add("confirm"); del.textContent = "Delete?";
        setTimeout(() => { del.classList.remove("confirm"); del.textContent = "🗑"; }, 3000);
        return;
      }
      try {
        await api(`/api/sessions/${s.id}`, { method: "DELETE", headers: { "X-Study-Buddy": "1" } });
        row.remove();
        if (!box.querySelector(".chat-row")) loadChats();
      } catch (err) { alert(`Couldn't delete: ${err.message}`); }
    };
    row.append(b, del);
    box.appendChild(row);
  }
}
async function openChat(s) {
  if (state.active) return;
  const r = await api(`/api/sessions/${s.id}/transcript`);
  showChat(s.title, s.id);
  $("#transcript").innerHTML = ""; state.lastRole = null;
  for (const m of r.transcript) {
    if (!m.text?.trim()) continue;
    bubble(m.role === "you" ? "you" : m.role === "tutor" ? "tutor" : "sys", m.text); state.lastRole = null;
  }
  if (!r.transcript.length) note("This chat has no saved messages.");
  note(`${when(r.started_at)} · ${CH[r.channel] || r.channel} · ${money(r.cost_total)}`);
  $("#mode").value = r.mode; setUI();
  clearBoard(); (r.boards || []).forEach((b) => showBoard(b));
  emit("sb:chat-open", { sid: s.id, title: s.title, recap: r.recap, turns: r.transcript.length });
}
const color = (m) => (m >= 0.75 ? "var(--good)" : m >= 0.45 ? "var(--warn)" : "var(--bad)");
async function loadProgress() {
  if (!state.course) return;
  const course = state.course;
  const { concepts } = await api(`/api/courses/${course}/progress`);
  if (course !== state.course) return;
  const el = $("#progress");
  if (!concepts.length) { el.innerHTML = `<span class="muted">No concepts yet — click “Build concept map”.</span>`; return; }
  el.innerHTML = concepts.map((c) => `
    <div class="concept"><span>${c.name}</span><span class="muted">${c.attempts ? Math.round(c.mastery * 100) + "%" : "—"}</span></div>
    <div class="bar"><span style="width:${Math.max(3, c.mastery * 100)}%;background:${color(c.mastery)}"></span></div>`).join("");
}
async function loadSpend() {
  const { month: m } = await api("/api/spend");
  const pct = Math.min(100, m.pct);
  $("#spend").innerHTML = `
    <div class="concept"><span>${money(m.spent)} of ${money(m.budget)}</span><span class="muted">${m.pct}%</span></div>
    <div class="bar"><span style="width:${Math.max(2, pct)}%;background:${pct >= 100 ? "var(--bad)" : pct >= 80 ? "var(--warn)" : "var(--good)"}"></span></div>
    <div class="muted">Today ${money(m.today)} · ${m.voice_minutes} premium-voice min · ${m.sessions} session${m.sessions === 1 ? "" : "s"}</div>
    ${pct >= 80 ? `<div class="warn">${pct >= 100 ? "Budget reached — premium voice is paused." : "Over 80% of budget — Economy voice charges for generated speech."}</div>` : ""}`;
}

// ---------- session lifecycle (all channels) ----------
const courseName = () => ((state.courses || []).find((c) => c.slug === state.course) || {}).name || "this class";
const openingLine = (resumed) => resumed
  ? `(Marc is back to continue our last chat in ${courseName()}. Say a quick, casual welcome back, remind him in one sentence where we left off, and ask if he wants to keep going. Don't start teaching yet.)`
  : `(Marc just opened a ${courseName()} session. Say a short, casual hi and ask what he wants to work on today. Don't start teaching, quizzing, or planning until he tells you.)`;
async function startSession(resumeSid = null) {
  if (!state.course) return note("Add a course folder first.", "err");
  $("#start").disabled = true;
  state.transcript = []; state.lastRole = null;
  $("#transcript").innerHTML = ""; clearBoard();
  emit("sb:chat-start", { resumed: !!resumeSid });
  const c = (state.courses || []).find((x) => x.slug === state.course) || {};
  state.active = true; showChat(`${resumeSid ? "Continuing · " : "New chat · "}${c.name || ""} · ${(state.cfg.modes || {})[$("#mode").value] || ""}`); state.active = false;
  pet.set("thinking");
  try {
    if (state.channel === "live") await startLive(resumeSid);
    else {
      if (state.channel === "economy" && !SpeechRec()) throw new Error("This browser has no speech recognition. Use Edge or Chrome.");
      const r = await post("/api/sessions/start", { course: state.course, mode: $("#mode").value, channel: state.channel, resume_sid: resumeSid });
      state.sid = r.sid; state.chatId = r.chat_id;
      onStarted();
      await brainTurn(openingLine(r.resumed), null, true);
      if (state.channel === "economy") listen();
    }
  } catch (err) { note(err.message, "err"); await teardown(false); }
}
function onStarted() {
  state.pageToldLive = state.pageToldBrain = null;
  state.active = true; state.startedAt = state.lastActivity = Date.now(); state.idleWarned = false;
  setUI(); state.timer = setInterval(tick, 1000);
  $("#backHome").hidden = true; $("#continueChat").hidden = true;
  pet.set(state.channel === "text" ? "idle" : "listening");
  note(state.channel === "live" ? "Premium voice live — talk naturally, interrupt any time." :
       state.channel === "economy" ? "Economy voice on — speak, pause, and it answers. Esc stops it talking." : "Text session started.");
}
async function endSession(reason = "") {
  if (!state.active) return;
  $("#start").disabled = true;
  if (state.channel === "live") {
    const closed = new Promise((res) => { state.closedResolve = res; setTimeout(res, 15000); });
    if (send({ type: "session.close", event_id: eid("close") })) await closed;
  }
  if (reason) note(reason);
  await teardown(true);
}
async function teardown(saveReceipt) {
  const measured = state.startedAt ? (Date.now() - state.startedAt) / 1000 : 0;
  const sid = state.sid;
  state.active = false; clearInterval(state.timer); clearInterval(state.micCheck); $("#micStatus").textContent = "";
  // live
  state.mic?.getTracks().forEach((t) => t.stop());
  try { state.dc?.close(); state.pc?.close(); } catch {}
  state.pc = state.dc = state.mic = null; state.pendingCalls = [];
  // economy
  stopListening(); cancelSpeech(); state.speaking = state.busy = false;
  pet.attachMic(null); pet.attachRemote(null); pet.set("sleep");
  setUI(); $("#backHome").hidden = false;
  if (saveReceipt && sid) {
    try {
      const r = await post(`/api/sessions/${sid}/close`, { measured_seconds: measured, client_usage: state.clientUsage, raw_usage: state.rawUsage, transcript: state.transcript, boards: state.boards });
      showReceipt(r); state.lastEndedSid = sid;
      emit("sb:chat-end", { sid, turns: state.transcript.length });
    } catch (err) { note(`Couldn't save the receipt: ${err.message}`, "err"); }
  }
  state.sid = null; state.chatId = null; state.rawUsage = null; state.seenResponses = new Set();
  state.clientUsage = { input_tokens: 0, output_tokens: 0, input_tokens_details: { cached_tokens: 0 } };
  loadProgress(); loadCourses(); loadSpend(); loadChats();
}
function tick() {
  const secs = (Date.now() - state.startedAt) / 1000, mins = secs / 60;
  const clock = `${Math.floor(mins)}:${String(Math.floor(secs % 60)).padStart(2, "0")}`;
  $("#meter").textContent = state.channel === "live" ? `${clock} · ~${money(mins * (state.cfg.price_live_per_min ?? 0.05))} voice so far` : clock;
  if (state.channel !== "live") return;
  if (mins >= state.cfg.max_session_minutes) return endSession(`Reached the ${state.cfg.max_session_minutes}-minute limit.`);
  const idle = (Date.now() - state.lastActivity) / 1000, limit = state.cfg.idle_end_seconds || 180;
  if (idle > limit - 30 && !state.idleWarned) { state.idleWarned = true; note("Quiet for a while — ending in 30s to save credits. Say something to keep going."); }
  if (idle > limit) endSession("Ended after inactivity. Hit “Resume” to pick up where you left off.");
}
function activity() { state.lastActivity = Date.now(); state.idleWarned = false; }
function setUI() {
  const a = state.active;
  $("#start").disabled = false;
  $("#start").textContent = a ? "End session" : "Start session";
  $("#start").className = a ? "danger" : "primary";
  $("#resume").hidden = a || !state.lastEndedSid || $("#chatView").hidden || !!state.viewingSid;
  $("#mute").disabled = !a || state.channel === "text";
  $("#mode").disabled = a; $("#micSelect").disabled = a;
  document.querySelectorAll(".seg button").forEach((b) => (b.disabled = a && !b.classList.contains("on")));
  if (!a) $("#meter").textContent = "";
}

// ---------- the page he's reading (synced by the browser extension) ----------
state.page = null; state.pageToldLive = null; state.pageToldBrain = null;
async function pollPage() {
  let m; try { m = await api("/api/page"); } catch { return; }
  const card = $("#pageCard");
  const old = state.page;
  if (!m.active) {
    card.hidden = true; state.page = null;
    if (old) emit("sb:page", m);
    return;
  }
  state.page = m; card.hidden = false;
  if (!old || m.hash !== old.hash || m.note_id !== old.note_id || m.has_selection !== old.has_selection || m.course !== old.course)
    emit("sb:page", m);
  card.classList.toggle("stale", m.age_seconds > 120);
  $("#pageTitle").textContent = m.title; $("#pageTitle").href = m.url;
  $("#pageInfo").textContent = `${m.chars.toLocaleString()} characters synced${m.has_selection ? " · you highlighted text" : ""}${m.activity ? " · lab/activity: available to your tutor while you work, no lesson breakdown" : ""}`;
  $("#pageAge").textContent = m.age_seconds < 10 ? "live" : `${Math.round(m.age_seconds / 60) ? Math.round(m.age_seconds / 60) + " min" : m.age_seconds + "s"} ago`;
  // Premium voice: a short silent heads-up whenever the page changes (not the text itself — the tutor reads it via read_page)
  if (state.active && state.channel === "live" && m.hash !== state.pageToldLive) {
    state.pageToldLive = m.hash;
    send({ type: "session.thinking.append", event_id: eid("page"), delegation_id: null,
      content: `Marc's browser is now on "${m.title}" (${m.url}). Its exact text is available through read_page — use it whenever he talks about what he's reading, instead of guessing.` });
  }
}
function pageNoteForBrain() {
  if (!state.page || state.page.hash === state.pageToldBrain) return "";
  state.pageToldBrain = state.page.hash;
  return `[Marc's browser is on "${state.page.title}" (${state.page.url}); its exact text is available via read_page.]\n\n`;
}
pollPage();
setInterval(pollPage, 2500);

// ---------- microphone: device choice + "is the tutor actually hearing me?" check ----------
function savedMic() { try { return localStorage.getItem("micId") || ""; } catch { return ""; } }
async function openMic(deviceId = savedMic()) {
  const base = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: deviceId ? { ...base, deviceId: { exact: deviceId } } : base });
  } catch (err) {
    if (deviceId) return navigator.mediaDevices.getUserMedia({ audio: base }); // saved mic unplugged -> default
    throw err;
  }
}
async function loadMics() {
  const sel = $("#micSelect");
  let devs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
  const cur = savedMic();
  sel.innerHTML = `<option value="">🎤 System default mic</option>` +
    devs.filter((d) => d.deviceId && d.deviceId !== "default").map((d, i) => `<option value="${esc(d.deviceId)}">🎤 ${esc(d.label || "Microphone " + (i + 1))}</option>`).join("");
  sel.value = devs.some((d) => d.deviceId === cur) ? cur : "";
}
async function testMic() {
  // 6-second check outside a session: Orbi's ring should pulse when you talk
  if (state.active) return;
  let stream;
  try { stream = await openMic(); } catch (err) { return note(`Can't open that mic: ${err.message}`, "err"); }
  await loadMics();
  const label = stream.getAudioTracks()[0]?.label || "mic";
  pet.attachMic(stream); pet.set("listening");
  $("#micStatus").textContent = `Testing ${label} — say something. Orbi's ring should pulse.`;
  setTimeout(() => { stream.getTracks().forEach((t) => t.stop()); pet.attachMic(null); if (!state.active) { pet.set("sleep"); $("#micStatus").textContent = ""; } }, 6000);
}
function startMicCheck() {
  const label = state.mic?.getAudioTracks()[0]?.label || "mic";
  let lastBytes = 0, loudSecs = 0, sentSecs = 0, warned = false; state.heardYou = false;
  clearInterval(state.micCheck);
  state.micCheck = setInterval(async () => {
    if (!state.pc) return;
    let bytes = 0, level = 0;
    (await state.pc.getStats()).forEach((r) => {
      if (r.type === "outbound-rtp" && r.kind === "audio") bytes = r.bytesSent || 0;
      if (r.type === "media-source" && r.kind === "audio") level = r.audioLevel || 0;
    });
    const sending = bytes > lastBytes; lastBytes = bytes;
    if (sending) sentSecs++;
    if (level > 0.02) loudSecs++;
    const track = state.mic?.getAudioTracks()[0];
    const ok = sending && track?.readyState === "live" && track.enabled;
    $("#micStatus").textContent = `🎤 ${label} · ${state.muted ? "muted" : ok ? "sending to tutor" : "NOT sending"}${state.heardYou ? " · tutor hears you ✓" : ""}`;
    if (warned || state.muted) return;
    if (sentSecs >= 6 && loudSecs === 0) { warned = true; note(`No sound is coming from “${label}”. Pick another mic in the 🎤 menu (end the session first), or check Windows sound settings.`, "err"); }
    else if (loudSecs >= 6 && !state.heardYou) { warned = true; note("Your mic is sending sound but the tutor isn't transcribing it yet. If it keeps talking over you, end the session and try Economy voice, then tell me what happened.", "err"); }
  }, 1000);
}

// ---------- premium voice: GPT-Live-1 over WebRTC ----------
function send(evt) {
  if (state.dc?.readyState !== "open") return false;
  state.dc.send(JSON.stringify(evt)); return true;
}
async function startLive(resumeSid) {
  note(resumeSid ? "Resuming…" : "Connecting…");
  const pc = new RTCPeerConnection(); state.pc = pc;
  pc.ontrack = (e) => { $("#remoteAudio").srcObject = e.streams[0]; pet.attachRemote(e.streams[0]); };
  state.mic = await openMic();
  pet.attachMic(state.mic);
  state.mic.getTracks().forEach((t) => pc.addTrack(t, state.mic));
  const dc = pc.createDataChannel("oai-events"); state.dc = dc;
  dc.onmessage = (e) => onEvent(JSON.parse(e.data));
  dc.onclose = () => { if (state.active) { note("Connection closed."); teardown(true); } };
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise((res) => {
    if (pc.iceGatheringState === "complete") return res();
    pc.addEventListener("icegatheringstatechange", () => pc.iceGatheringState === "complete" && res());
    setTimeout(res, 5000);
  });
  const r = await post("/api/live/session", { sdp: pc.localDescription.sdp, course: state.course, mode: $("#mode").value, resume_sid: resumeSid });
  state.sid = r.sid; state.chatId = r.chat_id; state.delegationMode = r.delegation_mode;
  await pc.setRemoteDescription({ type: "answer", sdp: r.sdp });
  state.resumed = r.resumed;
  // Over WebRTC the HTTP call already started the session — don't send session.start.
}
async function onEvent(ev) {
  switch (ev.type) {
    case "session.started":
      onStarted();
      // Make sure input isn't muted, then ask for a natural greeting. Per the GPT-Live docs the opening
      // line goes through session.instructions.append (not a forced backend response), so the voice
      // model stays in charge of turn-taking and keeps listening to the mic.
      send({ type: "session.input_audio.unmute", event_id: eid("unmute") });
      send({ type: "session.instructions.append", event_id: eid("greet"), delegation_id: null, content: openingLine(state.resumed) });
      startMicCheck();
      break;
    case "session.input_audio.unmuted": case "session.input_audio.muted": case "session.instructions.appended": break;
    case "session.input_transcript.delta": activity(); state.heardYou = true; say("you", ev.delta); state.userSinceDelegation += ev.delta; break;
    case "session.output_transcript.delta": activity(); say("tutor", ev.delta); pet.flash("speaking", 1400); emit("sb:turn"); break;
    case "session.delegation.created":
      if ((ev.delegation?.target || ev.target) === "client") clientDelegate(ev.delegation?.id ?? ev.delegation_id);
      break;
    case "response.event": onBackendEvent(ev.event || {}); break;
    case "error": note(`Error: ${ev.error?.message || JSON.stringify(ev.error)}`, "err"); break;
    case "session.closed": state.rawUsage = ev.usage || null; state.closedResolve?.(); break;
  }
}
function addUsage(u) {
  if (!u) return;
  state.clientUsage.input_tokens += u.input_tokens || 0;
  state.clientUsage.output_tokens += u.output_tokens || 0;
  state.clientUsage.input_tokens_details.cached_tokens += u.input_tokens_details?.cached_tokens || 0;
}
function onBackendEvent(e) {
  if (e.type === "response.output_item.done" && e.item?.type === "function_call") {
    activity(); pet.flash(e.item.name === "look_at_screen" ? "looking" : "thinking", 4000);
    state.pendingCalls.push(runCall(e.item));
  } else if (e.type === "response.completed" || e.type === "response.done") {
    const id = e.response?.id;
    if (id && !state.seenResponses.has(id)) { state.seenResponses.add(id); addUsage(e.response?.usage); }
    if (!state.pendingCalls.length) return;
    const calls = state.pendingCalls; state.pendingCalls = [];
    Promise.all(calls).then((results) => {
      for (const { call_id, output } of results)
        send({ type: "response.item.create", event_id: eid("tool"), item: { type: "function_call_output", call_id, output } });
      send({ type: "response.create", event_id: eid("continue") });
    });
  }
}
async function runCall(item) {
  let args = {}; try { args = JSON.parse(item.arguments || "{}"); } catch {}
  try {
    if (item.name === "show_on_board") { showBoard(args); return { call_id: item.call_id, output: '{"ok":true,"shown":true}' }; }
    if (item.name === "look_at_screen") {
      const seen = await look(args.question);
      return { call_id: item.call_id, output: JSON.stringify(seen ? { screen: seen.description, unchanged_since_last_look: seen.cached } : { error: "Marc isn't sharing his screen. Ask him to click 'Share screen'." }) };
    }
    const r = await post(`/api/tools/${state.course}/${item.name}`, args);
    if (item.name === "record_attempt") loadProgress();
    return { call_id: item.call_id, output: r.output };
  } catch (err) {
    return { call_id: item.call_id, output: JSON.stringify({ error: String(err.message || err) }) };
  }
}
async function clientDelegate(delegationId) {
  const text = state.userSinceDelegation.trim() || "(continue)"; state.userSinceDelegation = "";
  try {
    const screen = (await look(text))?.description;
    const r = await post("/api/chat", { course: state.course, mode: $("#mode").value, chat_id: state.chatId, text, screen });
    r.boards.forEach((b) => showBoard(b)); loadProgress();
    send({ type: "session.commentary.append", event_id: eid("brain"), delegation_id: delegationId, content: r.text.slice(0, 1800) });
  } catch (err) { note(`Brain error: ${err.message}`, "err"); }
}
function toggleMute() {
  if (!state.active || state.channel === "text") return;
  state.muted = !state.muted;
  if (state.channel === "live") {
    state.mic?.getAudioTracks().forEach((t) => (t.enabled = !state.muted));
    send({ type: state.muted ? "session.input_audio.mute" : "session.input_audio.unmute", event_id: eid("mute") });
  } else if (state.muted) stopListening(); else listen();
  $("#mute").textContent = state.muted ? "Unmute mic" : "Mute mic";
}

// ---------- economy voice: browser speech recognition + Luna + GPT-4o Mini TTS ----------
const SpeechRec = () => window.SpeechRecognition || window.webkitSpeechRecognition;
function listen() {
  if (state.channel !== "economy" || !state.active || state.muted || state.busy || state.speaking || state.listening) return;
  const R = SpeechRec(); const rec = new R(); state.rec = rec;
  pet.set("listening");
  rec.lang = "en-US"; rec.continuous = true; rec.interimResults = true;
  rec.onresult = (e) => {
    pet.flash("hearing", 900);
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) {
        const t = e.results[i][0].transcript.trim();
        if (t) { state.heard += (state.heard ? " " : "") + t; say("you", (state.lastRole === "you" ? " " : "") + t); }
        // Wait for a short pause so a multi-sentence thought goes as one turn.
        clearTimeout(state.sendTimer);
        state.sendTimer = setTimeout(flushHeard, 1300);
      }
    }
  };
  rec.onend = () => { state.listening = false; setTimeout(listen, 150); };
  rec.onerror = (e) => { if (e.error === "not-allowed") note("Microphone blocked — allow it in the browser.", "err"); };
  try { rec.start(); state.listening = true; } catch {}
}
function stopListening() { clearTimeout(state.sendTimer); try { state.rec?.abort(); } catch {} state.rec = null; state.listening = false; }
async function flushHeard() {
  const text = state.heard.trim(); state.heard = "";
  if (!text) return;
  // transcript entry was already streamed by say(); don't double-log
  stopListening(); await brainTurn(text, null, true, true);
}
function cancelSpeech() {
  state.ttsAbort?.abort();
  state.ttsAudio?.pause();
}
function speechChunks(text) {
  let remaining = text.replace(/[*_`#>]/g, "").trim();
  const chunks = [];
  while (remaining.length > 3800) {
    let end = remaining.lastIndexOf(" ", 3800);
    if (end < 1000) end = 3800;
    chunks.push(remaining.slice(0, end).trim());
    remaining = remaining.slice(end).trim();
  }
  if (remaining) chunks.push(remaining);
  return chunks;
}
async function speak(text) {
  const controller = new AbortController(); state.ttsAbort = controller;
  state.speaking = true; pet.set("speaking");
  const beat = setInterval(() => pet.pulse(0.5 + Math.random() * 0.4), 180);
  try {
    for (const chunk of speechChunks(text)) {
      if (controller.signal.aborted) break;
      const response = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sid: state.sid, text: chunk }), signal: controller.signal });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `Speech failed (${response.status})`);
      }
      const url = URL.createObjectURL(await response.blob());
      try {
        if (controller.signal.aborted) break;
        const audio = new Audio(url); state.ttsAudio = audio;
        await new Promise((resolve, reject) => {
          audio.onended = resolve; audio.onpause = resolve; audio.onerror = () => reject(new Error("Could not play speech audio."));
          audio.play().catch(reject);
        });
      } finally { state.ttsAudio = null; URL.revokeObjectURL(url); }
    }
  } catch (err) {
    if (!controller.signal.aborted) throw err;
  } finally {
    clearInterval(beat); state.ttsAbort = null; state.speaking = false;
  }
}

// ---------- brain turns (text + economy) ----------
async function brainTurn(text, image = null, hidden = false, alreadyLogged = false) {
  if (!hidden) {
    const el = bubble("you", text || ""); state.lastRole = null;
    if (image) { const i = document.createElement("img"); i.src = image; el.appendChild(i); }
  }
  if (!alreadyLogged && !hidden) logTurn("you", text || "[image]");
  state.busy = true; pet.set("thinking");
  const thinking = bubble("sys", "thinking…");
  try {
    const screen = (await look(text))?.description;
    const r = await post("/api/chat", { course: state.course, mode: $("#mode").value, chat_id: state.chatId, text: pageNoteForBrain() + text, image, screen });
    state.chatId = r.chat_id; state.sid = state.sid || r.sid;
    thinking.remove(); r.boards.forEach((b) => showBoard(b));
    bubble("tutor", r.text); state.lastRole = null; logTurn("tutor", r.text); loadProgress(); emit("sb:turn");
    if (state.channel === "economy" && state.active) await speak(r.text);
  } catch (err) { thinking.remove(); note(err.message, "err"); }
  state.busy = false;
  if (state.active) pet.set(state.channel === "text" ? "idle" : "listening"); else pet.set("sleep");
  if (state.channel === "economy") listen();
}

// ---------- eyes: screen sharing with change detection ----------
async function toggleScreen() {
  if (state.screen) return stopScreen();
  try {
    state.screen = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 2 }, audio: false });
  } catch { return note("Screen sharing was cancelled."); }
  const v = document.createElement("video"); v.muted = true; v.srcObject = state.screen; await v.play(); state.video = v;
  state.screen.getVideoTracks()[0].onended = stopScreen;
  $("#share").textContent = "👁 Stop sharing"; $("#share").classList.add("on"); $("#lookNow").disabled = false;
  $("#eyes").hidden = false; state.lastLook = null;
  note("The tutor can now see your screen when it needs to (only when it looks).");
}
function stopScreen() {
  state.screen?.getTracks().forEach((t) => t.stop());
  state.screen = state.video = state.lastLook = null;
  $("#share").textContent = "👁 Share screen"; $("#share").classList.remove("on"); $("#lookNow").disabled = true;
  $("#eyes").hidden = true;
}
function grab(maxW = 1280, quality = 0.7) {
  const v = state.video, scale = Math.min(1, maxW / v.videoWidth);
  const c = document.createElement("canvas"); c.width = v.videoWidth * scale; c.height = v.videoHeight * scale;
  c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
  // 9x8 difference hash: 64 bits that change only when the screen meaningfully changes
  const h = document.createElement("canvas"); h.width = 9; h.height = 8;
  const hx = h.getContext("2d", { willReadFrequently: true }); hx.drawImage(v, 0, 0, 9, 8);
  const px = hx.getImageData(0, 0, 9, 8).data, gray = (i) => px[i] * 0.3 + px[i + 1] * 0.59 + px[i + 2] * 0.11;
  let bits = "";
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) bits += gray((y * 9 + x) * 4) > gray((y * 9 + x + 1) * 4) ? "1" : "0";
  return { url: c.toDataURL("image/jpeg", quality), hash: bits };
}
const hamming = (a, b) => { let d = 0; for (let i = 0; i < a.length; i++) d += a[i] !== b[i]; return d; };
async function look(question = "", force = false) {
  if (!state.screen || !state.video?.videoWidth) return null;
  const { url, hash } = grab();
  $("#eyesImg").src = url;
  if (!force && state.lastLook && hamming(hash, state.lastLook.hash) <= 3) {
    $("#eyesInfo").textContent = "Screen unchanged — reused last look (free)";
    return { description: state.lastLook.description, cached: true };
  }
  $("#eyesInfo").textContent = "Looking…"; pet.flash("looking", 2500);
  const r = await post("/api/vision/describe", { image: url, question, sid: state.sid });
  state.lastLook = { hash, description: r.description };
  $("#eyesInfo").textContent = `Fresh look · ${money(r.cost)}`;
  return { description: r.description, cached: false };
}
async function lookNow() {
  if (!state.active) return note("Start a session first.");
  if (state.channel === "live") {
    const seen = await look("What is Marc looking at and what does he need help with?", true).catch((e) => note(e.message, "err"));
    if (!seen) return;
    bubble("you", "📸 (showed my screen)"); state.lastRole = null; logTurn("you", "[showed screen]");
    send({ type: "response.item.create", event_id: eid("look"), item: { type: "message", role: "user", content: [{ type: "input_text", text: `[Marc's screen right now: ${seen.description}]\nTake a look at this with me.` }] } });
    send({ type: "response.create", event_id: eid("go") });
  } else {
    state.lastLook = null; stopListening();
    await brainTurn("Take a look at my screen with me.");
  }
}

// ---------- typed input + pasted screenshots ----------
// Screenshots are read once into text context (what's on them, transcribed) and then thrown away:
// the image itself is never saved and never kept in either model's conversation.
state.pending = [];
async function shrinkImage(file, maxSide = 1920, maxBytes = 900_000) {
  const img = await createImageBitmap(file);
  let scale = Math.min(1, maxSide / Math.max(img.width, img.height)), q = 0.88, url;
  const c = document.createElement("canvas");
  do {
    c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    url = c.toDataURL("image/jpeg", q);
    q -= 0.1; if (q < 0.5) { scale *= 0.8; q = 0.8; }
  } while (url.length > maxBytes && scale > 0.2);
  img.close?.();
  return url;
}
async function addPending(files) {
  const imgs = [...files].filter((f) => f && f.type?.startsWith("image/"));
  if (!imgs.length) return false;
  for (const f of imgs.slice(0, Math.max(0, 4 - state.pending.length))) state.pending.push(await shrinkImage(f));
  if (imgs.length + state.pending.length > 4) note("Up to 4 screenshots per message.");
  renderPending(); $("#text").focus();
  return true;
}
function renderPending() {
  const box = $("#attachments"); box.innerHTML = "";
  box.hidden = !state.pending.length;
  state.pending.forEach((url, i) => {
    const chip = document.createElement("div"); chip.className = "chip";
    chip.innerHTML = `<img alt="screenshot ${i + 1}"><button type="button" title="Remove">✕</button>`;
    chip.querySelector("img").src = url;
    chip.querySelector("button").onclick = () => { state.pending.splice(i, 1); renderPending(); };
    box.appendChild(chip);
  });
  if (state.pending.length) box.insertAdjacentHTML("beforeend", `<span class="muted small">Screenshot${state.pending.length > 1 ? "s" : ""} will be read into text for the tutor, then discarded. Add a question or just press Enter.</span>`);
}
async function readScreenshots(images, question) {
  const out = [];
  for (const [i, url] of images.entries()) {
    const r = await post("/api/vision/describe", { image: url, question, sid: state.sid, kind: "paste" });
    out.push(images.length > 1 ? `Screenshot ${i + 1}: ${r.description}` : r.description);
  }
  return out.join("\n\n");
}
async function ensureSession() {
  if (state.active) return;
  if (!state.course) throw new Error("Pick a course first.");
  const resume = state.viewingSid; // typing in a past chat continues it
  if (state.channel === "live") setChannel("text");
  $("#transcript").innerHTML = ""; state.transcript = [];
  const r = await post("/api/sessions/start", { course: state.course, mode: $("#mode").value, channel: state.channel, resume_sid: resume });
  state.sid = r.sid; state.chatId = r.chat_id;
  state.active = true; showChat(resume ? "Continuing chat" : "New text chat"); onStarted();
}
async function submit(text) {
  const images = state.pending.splice(0); renderPending();
  if (!text && !images.length) return;
  try { await ensureSession(); } catch (err) { return note(err.message, "err"); }
  // show it (thumbnails live only in this page, never saved)
  const el = bubble("you", text || ""); state.lastRole = null;
  images.forEach((u) => { const im = document.createElement("img"); im.src = u; el.appendChild(im); });
  logTurn("you", (images.length ? `[shared ${images.length > 1 ? images.length + " screenshots" : "a screenshot"}] ` : "") + (text || ""));
  activity(); stopListening();
  let message = text || "";
  if (images.length) {
    const reading = bubble("sys", `reading screenshot${images.length > 1 ? "s" : ""}…`); pet.flash("looking", 6000);
    try {
      const ctx = await readScreenshots(images, text);
      message = `[Marc pasted ${images.length > 1 ? "screenshots" : "a screenshot"}. What's on ${images.length > 1 ? "them" : "it"}: ${ctx}]\n\n` +
        (text || "Help me with this — coach me, don't just give me the answer.");
      reading.textContent = `read screenshot${images.length > 1 ? "s" : ""} ✓`;
    } catch (err) { reading.remove(); note(err.message, "err"); if (!text) return; }
  }
  if (state.channel === "live") {
    send({ type: "response.item.create", event_id: eid("typed"), item: { type: "message", role: "user", content: [{ type: "input_text", text: message }] } });
    send({ type: "response.create", event_id: eid("go") });
    return;
  }
  await brainTurn(message, null, true, true);
}

// ---------- wiring ----------
function setChannel(ch) {
  if (state.active) return note("End the session before switching.");
  state.channel = ch;
  document.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("on", b.dataset.ch === ch));
  $("#channelHint").textContent = { live: "Best conversation · ~$3/hr", economy: "Luna + AI-generated Mini TTS · billed for speech generated", text: "Type · ~pennies/hr" }[ch];
  setUI();
}
document.querySelectorAll(".seg button").forEach((b) => (b.onclick = () => setChannel(b.dataset.ch)));
$("#start").onclick = () => (state.active ? endSession() : startSession());
$("#resume").onclick = () => startSession(state.lastEndedSid);
$("#continueChat").onclick = () => startSession(state.viewingSid);
$("#backHome").onclick = () => { showHome(); setUI(); };
$("#mute").onclick = toggleMute;

$("#micSelect").onchange = async (e) => { try { localStorage.setItem("micId", e.target.value); } catch {} await testMic(); };
navigator.mediaDevices?.addEventListener?.("devicechange", () => loadMics().catch(() => {}));
$("#share").onclick = toggleScreen;
$("#lookNow").onclick = lookNow;
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.code === "Space") { e.preventDefault(); toggleMute(); }
  if (e.key === "Escape" && state.speaking) { cancelSpeech(); }
});
$("#composer").onsubmit = (e) => { e.preventDefault(); const t = $("#text").value.trim(); $("#text").value = ""; submit(t); };
$("#image").onchange = async (e) => { await addPending(e.target.files); e.target.value = ""; };
// Ctrl+V a screenshot anywhere (except the About-me box), or drag an image onto the window
document.addEventListener("paste", async (e) => {
  if (e.target.closest?.("#aboutWrap, .pet-name")) return;
  const files = [...(e.clipboardData?.items || [])].filter((it) => it.kind === "file").map((it) => it.getAsFile());
  if (files.some((f) => f?.type?.startsWith("image/"))) { e.preventDefault(); await addPending(files); }
});
document.addEventListener("dragover", (e) => { if ([...(e.dataTransfer?.items || [])].some((it) => it.type?.startsWith("image/"))) { e.preventDefault(); document.body.classList.add("dropping"); } });
document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) document.body.classList.remove("dropping"); });
document.addEventListener("drop", async (e) => { document.body.classList.remove("dropping"); if (e.dataTransfer?.files?.length) { e.preventDefault(); await addPending(e.dataTransfer.files); } });
$("#reindex").onclick = async () => { if (!state.course) return; const s = await post(`/api/courses/${state.course}/index`); note(`Indexed: ${s.added} new, ${s.updated} changed, ${s.removed} removed${s.errors.length ? ", errors: " + s.errors.join("; ") : ""}`); loadCourses(); };
$("#buildConcepts").onclick = async () => {
  if (!state.course) return; note("Luna is reading the course material to build the concept map (Flex tier — cheaper, can take a few minutes)…");
  try { const r = await post(`/api/courses/${state.course}/concepts/build`); note(`Concept map: ${r.added_or_updated} concepts · cost ${money(r.cost)}`); loadProgress(); loadCourses(); loadSpend(); }
  catch (err) { note(err.message, "err"); }
};
$("#saveAbout").onclick = async () => { await api("/api/about_me", { method: "PUT", body: JSON.stringify({ text: $("#aboutMe").value }) }); note("Saved — new sessions will use it."); };
window.addEventListener("beforeunload", () => { if (state.active && state.sid) navigator.sendBeacon?.(`/api/sessions/${state.sid}/close`, new Blob([JSON.stringify({ measured_seconds: (Date.now() - state.startedAt) / 1000, client_usage: state.clientUsage, transcript: state.transcript })], { type: "application/json" })); });

(async () => {
  try {
    await loadStatus(); await loadCourses(); await loadSpend(); setChannel("live");
    loadMics().catch(() => {});
    $("#aboutMe").value = (await api("/api/about_me")).text;
  } catch (err) { note(err.message, "err"); }
})();
