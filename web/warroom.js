// The war room (right side): per-chat recap + board, course notes, course study guide.
// Uses shared.js helpers and chat state/events from app.js.
(() => {
  const W = { tab: "war", sid: null, recapBusy: false, lastRecapTurns: 0, lastRecapAt: 0, notes: [], filter: "", summaryWatch: null, practice: new Map(), tests: [], test: null, testWatch: null, testPolls: 0 };

  // ---------- tabs ----------
  function showTab(name) {
    W.tab = name;
    document.querySelectorAll("#warPane .tabs button[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
    for (const t of ["war", "notes", "tests", "guide"]) $(`#tab-${t}`).hidden = t !== name;
    if (name === "tests") { W.testPolls = 0; loadTests(); }
    try { localStorage.setItem("warTab", name); } catch {}
  }
  document.querySelectorAll("#warPane .tabs button[data-tab]").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  try { const t = localStorage.getItem("warTab"); if (t) showTab(t); } catch {}

  const ago = (iso) => {
    if (!iso) return "";
    const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(iso).toLocaleDateString();
  };

  // ---------- war room: recap for the open chat ----------
  function renderRecap(rc) {
    const box = $("#recap");
    if (!rc) { box.innerHTML = `<div class="empty">The recap builds up here as you talk — what you covered, key terms, what clicked, your weak spots, and quick-check cards.</div>`; $("#recapAge").textContent = ""; return; }
    const list = (xs) => `<ul>${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    let html = "";
    if (rc.covered?.length) html += `<div class="rc-block"><h3>What we covered</h3>${list(rc.covered)}</div>`;
    if (rc.key_terms?.length) html += `<div class="rc-block"><h3>Key terms, plain words</h3><div class="terms">${rc.key_terms.map((t) => `<b>${esc(t.term)}</b><span>${esc(t.plain)}</span>`).join("")}</div></div>`;
    if (rc.clicked?.length) html += `<div class="rc-block"><h3>What clicked</h3>${list(rc.clicked)}</div>`;
    if (rc.weak_spots?.length) html += `<div class="rc-block"><h3>Your weak spots</h3>${rc.weak_spots.map((w) => `<div class="weak"><div>${esc(w.issue)}</div><div class="fix">→ ${esc(w.fix)}</div></div>`).join("")}</div>`;
    if (rc.quick_checks?.length) html += `<div class="rc-block"><h3>Quick checks</h3><div class="qcards">${rc.quick_checks.map((q) => `<button class="qcard"><div>${esc(q.q)}</div><div class="a">${esc(q.a)}</div><div class="hint">tap to reveal</div></button>`).join("")}</div></div>`;
    if (rc.next_up) html += `<div class="rc-block"><h3>Next up</h3><div class="next-up">${esc(rc.next_up)}</div></div>`;
    box.innerHTML = html || `<div class="empty">Not much to recap yet — keep going.</div>`;
    box.querySelectorAll(".qcard").forEach((c) => (c.onclick = () => c.classList.toggle("show")));
    $("#recapAge").textContent = rc.updated_at ? `recap updated ${ago(rc.updated_at)}` : "";
    if (rc.title) $("#warTitle").textContent = rc.title;
  }

  async function updateRecap({ live = state.active, quiet = false } = {}) {
    const sid = live ? state.sid : W.sid;
    if (!sid || W.recapBusy) return;
    W.recapBusy = true; $("#updateRecap").disabled = true; $("#recapAge").textContent = "updating recap…";
    try {
      const rc = await post(`/api/sessions/${sid}/recap`, live ? { transcript: state.transcript, boards: state.boards } : {});
      if ((live ? state.sid : W.sid) === sid) renderRecap(rc);
      W.lastRecapTurns = state.transcript.length; W.lastRecapAt = Date.now();
    } catch (err) {
      if (!quiet) note(err.message, "err");
      $("#recapAge").textContent = "";
    } finally { W.recapBusy = false; $("#updateRecap").disabled = false; }
  }
  $("#updateRecap").onclick = () => updateRecap();

  // During a chat: refresh the recap every few exchanges (cheap: ~a tenth of a cent each)
  let turnTimer = null;
  window.addEventListener("sb:turn", () => {
    clearTimeout(turnTimer);
    turnTimer = setTimeout(() => {
      if (!state.active) return;
      const newTurns = state.transcript.length - W.lastRecapTurns;
      const since = Date.now() - W.lastRecapAt;
      if ((newTurns >= 4 && since > 40_000) || (newTurns >= 2 && since > 120_000)) updateRecap({ live: true, quiet: true });
    }, 5000);
  });
  window.addEventListener("sb:chat-start", (e) => {
    W.sid = null; W.lastRecapTurns = 0; W.lastRecapAt = Date.now();
    $("#warTitle").textContent = e.detail.resumed ? "Continuing chat" : "New chat";
    renderRecap(null);
  });
  window.addEventListener("sb:chat-end", async (e) => {
    W.sid = e.detail.sid;
    if (e.detail.turns >= 2) { await updateRecap({ live: false, quiet: true }); if (typeof loadChats === "function") loadChats(); }
  });
  window.addEventListener("sb:chat-open", (e) => {
    W.sid = e.detail.sid; $("#warTitle").textContent = e.detail.title || "Chat";
    renderRecap(e.detail.recap);
    if (!e.detail.recap && e.detail.turns >= 2) updateRecap({ live: false, quiet: true }); // build it the first time
    showTab("war");
  });

  // ---------- lesson practice ----------
  const practiceKey = (n) => `${state.course}:${n.id}`;
  function practiceBox(n) {
    return [...document.querySelectorAll("#notesList details.note")].find((d) => d.dataset.id === n.id)?.querySelector(".practice-body");
  }
  async function startPractice(n, force = false) {
    const course = state.course, key = practiceKey(n);
    W.practice.set(key, { loading: true }); renderPractice(n);
    try {
      const data = await post(`/api/courses/${course}/note/practice?id=${encodeURIComponent(n.id)}${force ? "&force=true" : ""}`);
      if (course !== state.course) return;
      W.practice.set(key, { data, sourceUpdated: n.updated, mode: "cards", cardIndex: 0, quizIndex: 0, revealed: false, answers: {}, busy: false });
      renderPractice(n);
      if (data.cost && typeof loadSpend === "function") loadSpend();
    } catch (err) {
      if (course !== state.course) return;
      W.practice.set(key, { error: err.message }); renderPractice(n);
    }
  }
  function ensurePractice(n) {
    if (!W.practice.has(practiceKey(n))) startPractice(n);
    else renderPractice(n);
  }
  function renderPractice(n) {
    const box = practiceBox(n), p = W.practice.get(practiceKey(n));
    if (!box || !p) return;
    if (p.loading) { box.innerHTML = `<div class="muted small">Building lesson flashcards and quiz questions…</div>`; return; }
    if (p.error) {
      box.innerHTML = `<div class="err small">${esc(p.error)}</div><button class="ghost retry-practice">Try again</button>`;
      box.querySelector(".retry-practice").onclick = () => startPractice(n);
      return;
    }
    const cards = p.data.cards, quiz = p.data.quiz, isCard = p.mode === "cards";
    const items = isCard ? cards : quiz, index = isCard ? p.cardIndex : p.quizIndex;
    const answered = items.filter((item) => p.answers[item.id]);
    const got = answered.filter((item) => p.answers[item.id].outcome === "got_it").length;
    let html = `<div class="practice-tabs"><button class="${isCard ? "on" : ""}" data-mode="cards">Flashcards</button><button class="${!isCard ? "on" : ""}" data-mode="quiz">Mini quiz</button></div>`;
    if (index >= items.length) {
      html += `<div class="practice-result"><strong>${isCard ? "Flashcards complete" : "Quiz complete"}</strong><div>${got} of ${items.length} ${isCard ? "marked Got it" : "correct"}. Your answers updated the concept map and class progress.</div><div class="practice-actions"><button class="ghost restart-practice">Try again</button><button class="ghost new-practice">New questions</button></div></div>`;
    } else {
      const item = items[index], feedback = p.answers[item.id];
      html += `<div class="practice-count">${index + 1} of ${items.length} · ${esc(item.concept_name)}</div>`;
      if (isCard) {
        html += `<div class="practice-prompt">${esc(item.front)}</div>`;
        if (!p.revealed && !feedback) html += `<button class="primary reveal-card">Show answer</button>`;
        else {
          html += `<div class="practice-answer"><b>Answer</b><div>${esc(item.back)}</div></div>`;
          if (!feedback) html += `<div class="muted small">How well could you recall it before flipping?</div><div class="practice-actions"><button class="rate-card" data-rating="got_it">Got it</button><button class="rate-card" data-rating="partial">Almost</button><button class="rate-card" data-rating="missed">Again</button></div>`;
        }
      } else {
        html += `<div class="practice-prompt">${esc(item.question)}</div><div class="practice-options">${item.options.map((option, i) => `<button data-choice="${i}" ${feedback ? "disabled" : ""} class="${feedback ? i === feedback.correct_index ? "correct" : i === feedback.choice ? "incorrect" : "" : ""}">${esc(option)}</button>`).join("")}</div>`;
      }
      if (feedback) html += `<div class="practice-feedback ${feedback.outcome === "got_it" ? "right" : "wrong"}"><strong>${feedback.outcome === "got_it" ? "Got it" : feedback.outcome === "partial" ? "Almost" : "Review this one"}</strong><div>${esc(feedback.explanation)}</div><div class="muted small">${esc(item.concept_name)} mastery: ${Math.round(feedback.mastery * 100)}%</div></div><button class="primary next-practice">${index + 1 === items.length ? "See results" : "Next"}</button>`;
    }
    box.innerHTML = html;
    box.querySelectorAll(".practice-tabs button").forEach((b) => b.onclick = () => { p.mode = b.dataset.mode; renderPractice(n); });
    box.querySelector(".reveal-card")?.addEventListener("click", () => { p.revealed = true; renderPractice(n); });
    box.querySelectorAll(".rate-card").forEach((b) => b.onclick = () => submitPractice(n, items[index], { rating: b.dataset.rating }));
    box.querySelectorAll(".practice-options button").forEach((b) => b.onclick = () => submitPractice(n, items[index], { choice: Number(b.dataset.choice) }));
    box.querySelector(".next-practice")?.addEventListener("click", () => {
      if (isCard) { p.cardIndex++; p.revealed = false; } else p.quizIndex++;
      renderPractice(n);
    });
    box.querySelector(".restart-practice")?.addEventListener("click", () => startPractice(n));
    box.querySelector(".new-practice")?.addEventListener("click", () => startPractice(n, true));
  }
  async function submitPractice(n, item, answer) {
    const course = state.course, p = W.practice.get(practiceKey(n));
    if (!p || p.busy || p.answers[item.id]) return;
    p.busy = true;
    const box = practiceBox(n);
    box?.querySelectorAll(".rate-card, .practice-options button").forEach((b) => b.disabled = true);
    try {
      const feedback = await post(`/api/courses/${course}/note/practice/answer?id=${encodeURIComponent(n.id)}`,
        { run_id: p.data.run_id, item_id: item.id, ...answer });
      if (course !== state.course) return;
      p.answers[item.id] = feedback; renderPractice(n);
      if (typeof loadProgress === "function") loadProgress();
      if (typeof loadCourses === "function") loadCourses();
    } catch (err) { if (course === state.course) { toast(err.message, "err"); renderPractice(n); } }
    finally { p.busy = false; }
  }

  // ---------- full lesson tests ----------
  async function loadTests() {
    if (!state.course) return;
    const course = state.course;
    try {
      const rows = await api(`/api/courses/${course}/tests`);
      if (course !== state.course) return;
      W.tests = rows; renderTests();
      clearTimeout(W.testWatch);
      if (W.tab === "tests" && rows.some((n) => !n.ready) && W.testPolls++ < 72)
        W.testWatch = setTimeout(loadTests, 5000);
    } catch (err) { if (course === state.course) $("#lessonTests").innerHTML = `<div class="err">${esc(err.message)}</div>`; }
  }
  function renderTests() {
    const box = $("#lessonTests");
    if (!W.tests.length) {
      box.innerHTML = `<div class="empty">Save a lesson page to see its test here. New lesson tests are generated after the page is saved and broken down.</div>`;
      return;
    }
    box.innerHTML = W.tests.map((n, i) => `<div class="lesson-test-row">
      <div><strong>${n.section ? `<span class="sec">${esc(n.section)}</span>` : ""}${esc(n.title)}</strong>
      <div class="muted small">${n.ready ? `${n.questions} questions ready` : esc(n.status)}</div></div>
      <div class="practice-actions"><button class="primary start-test" data-i="${i}" ${n.ready ? "" : "disabled"}>Take test</button>
      <button class="ghost new-test" data-i="${i}">${n.ready ? "Regenerate questions" : "Generate test"}</button></div></div>`).join("");
    box.querySelectorAll(".start-test").forEach((b) => b.onclick = () => startTest(W.tests[Number(b.dataset.i)]));
    box.querySelectorAll(".new-test").forEach((b) => b.onclick = () => startTest(W.tests[Number(b.dataset.i)], true));
  }
  async function startTest(n, force = false) {
    const course = state.course;
    W.test = { note: n, loading: true, data: null, index: 0, answers: {}, busy: false };
    renderTest();
    try {
      const data = await post(`/api/courses/${course}/note/test?id=${encodeURIComponent(n.id)}${force ? "&force=true" : ""}`);
      if (course !== state.course) return;
      W.test = { note: n, loading: false, data, index: 0, answers: {}, busy: false };
      renderTest(); loadTests();
      if (data.cost && typeof loadSpend === "function") loadSpend();
    } catch (err) {
      if (course !== state.course) return;
      W.test.error = err.message; W.test.loading = false; renderTest();
    }
  }
  function renderTest() {
    const t = W.test, box = $("#lessonTestRun");
    if (!t) { box.innerHTML = ""; return; }
    if (t.loading) { box.innerHTML = `<div class="practice lesson-test-run"><div class="muted">${t.note.ready ? "Starting test…" : "Luna is generating this lesson's test…"}</div></div>`; return; }
    if (t.error) { box.innerHTML = `<div class="practice lesson-test-run"><div class="err">${esc(t.error)}</div><button class="ghost close-test">Close</button></div>`; box.querySelector(".close-test").onclick = () => { W.test = null; renderTest(); }; return; }
    const items = t.data.quiz, index = t.index, answered = items.filter((item) => t.answers[item.id]);
    const got = answered.filter((item) => t.answers[item.id].outcome === "got_it").length;
    let html = `<div class="practice lesson-test-run"><div class="tab-head"><div><div class="tab-title">${esc(t.note.title)}</div><div class="muted small">${answered.length} of ${items.length} answered · answers update your concept map</div></div><button class="ghost close-test">Close</button></div>`;
    if (index >= items.length) {
      html += `<div class="practice-result"><strong>Test complete: ${got} of ${items.length} correct</strong><div>Your answers updated the concept map and class progress.</div><div class="practice-actions"><button class="primary retake-test">Retake with shuffled answers</button><button class="ghost regenerate-test">Regenerate questions</button></div></div>`;
    } else {
      const item = items[index], feedback = t.answers[item.id];
      html += `<div class="practice-count">Question ${index + 1} of ${items.length} · ${esc(item.concept_name)}</div>
        <div class="practice-prompt">${esc(item.question)}</div><div class="practice-options">${item.options.map((option, i) => `<button data-choice="${i}" ${feedback ? "disabled" : ""} class="${feedback ? i === feedback.correct_index ? "correct" : i === feedback.choice ? "incorrect" : "" : ""}">${String.fromCharCode(65 + i)}. ${esc(option)}</button>`).join("")}</div>`;
      if (feedback) html += `<div class="practice-feedback ${feedback.outcome === "got_it" ? "right" : "wrong"}"><strong>${feedback.outcome === "got_it" ? "Correct" : "Review this one"}</strong><div>${esc(feedback.explanation)}</div><div class="muted small">${esc(item.concept_name)} mastery: ${Math.round(feedback.mastery * 100)}%</div></div><button class="primary next-test">${index + 1 === items.length ? "See results" : "Next question"}</button>`;
    }
    box.innerHTML = html + `</div>`;
    box.querySelector(".close-test").onclick = () => { W.test = null; renderTest(); };
    box.querySelectorAll(".practice-options button").forEach((b) => b.onclick = () => submitTest(items[index], Number(b.dataset.choice)));
    box.querySelector(".next-test")?.addEventListener("click", () => { t.index++; renderTest(); });
    box.querySelector(".retake-test")?.addEventListener("click", () => startTest(t.note));
    box.querySelector(".regenerate-test")?.addEventListener("click", () => startTest(t.note, true));
  }
  async function submitTest(item, choice) {
    const t = W.test, course = state.course;
    if (!t || t.busy || t.answers[item.id]) return;
    t.busy = true;
    $("#lessonTestRun").querySelectorAll(".practice-options button").forEach((b) => b.disabled = true);
    try {
      const feedback = await post(`/api/courses/${course}/note/practice/answer?id=${encodeURIComponent(t.note.id)}`,
        { run_id: t.data.run_id, item_id: item.id, choice });
      if (course !== state.course || t !== W.test) return;
      t.answers[item.id] = feedback; renderTest();
      if (typeof loadProgress === "function") loadProgress();
      if (typeof loadCourses === "function") loadCourses();
    } catch (err) { if (course === state.course) { toast(err.message, "err"); renderTest(); } }
    finally { t.busy = false; }
  }

  // ---------- notes tab ----------
  async function loadNotes() {
    if (!state.course) return;
    const course = state.course;
    let notes; try { notes = await api(`/api/courses/${course}/notes`); } catch { return; }
    if (course !== state.course) return;
    for (const n of notes) {
      const key = practiceKey(n), entry = W.practice.get(key);
      if (entry?.sourceUpdated && entry.sourceUpdated !== n.updated) W.practice.delete(key);
    }
    W.notes = notes;
    renderNotes();
  }
  function renderNotes() {
    const course = state.course;
    const list = $("#notesList");
    const open = new Set([...list.querySelectorAll("details.note[open]")].map((d) => d.dataset.id));
    const f = W.filter.toLowerCase();
    const items = W.notes.filter((n) => !f || n.title.toLowerCase().includes(f) || (n.my_notes || "").toLowerCase().includes(f) || (n.section || "").includes(f));
    $("#notesCount").textContent = `${W.notes.length} note${W.notes.length === 1 ? "" : "s"} · ${W.notes.filter((n) => n.summary).length} broken down`;
    if (!W.notes.length) {
      list.innerHTML = `<div class="empty">No notes for this course yet. Open a lesson in Chrome, click the Study Buddy extension → <b>Follow this tab</b>, then <b>Save &amp; summarize</b> (or turn on Auto-save). Files you put in the course's <code>material</code> folder show up here too.</div>`;
      return;
    }
    list.innerHTML = "";
    for (const n of items) {
      const d = document.createElement("details"); d.className = "note"; d.dataset.id = n.id;
      if (open.has(n.id)) d.open = true;
      d.innerHTML = `<summary>${n.section ? `<span class="sec">${esc(n.section)}</span>` : ""}<span class="nt">${esc(n.section && n.title.startsWith(n.section) ? n.title.slice(n.section.length).trim() : n.title)}</span>
        <span class="nm">${n.my_notes ? "✎ " : ""}${n.summary ? "breakdown ✓" : n.kind === "page" ? "breaking down…" : esc(n.kind || "")}</span></summary>
        <div class="nb">
          <div class="practice"><div class="label"><span>Flashcards &amp; mini quiz</span><span class="muted">Answers update concept progress</span></div><div class="practice-body"></div></div>
          <div class="label"><span>Breakdown</span><span>${n.summary ? `<a href="#" class="resum">redo breakdown</a>` : ""}</span></div>
          <div class="md breakdown">${n.summary ? "" : `<button class="ghost do-sum">✨ Break it down</button> <span class="muted small">the one big idea, a comparison table, traps, and a quick self-test (about 250 words)</span>`}</div>
          <button class="ghost show-fullnotes" type="button">Full notes ▸</button><div class="md fullnotes" hidden></div>
          <div class="label"><span>My notes</span><span class="saved muted"></span></div>
          <textarea class="mine" placeholder="Your own notes for this section — what clicked, questions for class, mnemonics…"></textarea>
          <div class="label"><span>Full text</span><span>${n.source_url ? `<a href="${esc(n.source_url)}" target="_blank" rel="noopener">open source ↗</a>` : ""}</span></div>
          <button class="ghost show-full">Show original text</button><div class="full" hidden></div>
          ${n.kind === "page" ? `<div class="note-actions"><button class="ghost delete-lesson" type="button">Delete lesson</button></div>` : ""}
        </div>`;
      if (n.summary) renderMd(d.querySelector(".breakdown"), n.summary);
      const ta = d.querySelector("textarea.mine"); ta.value = n.my_notes || "";
      let t; ta.oninput = () => {
        d.querySelector(".saved").textContent = "…";
        clearTimeout(t); t = setTimeout(async () => {
          try { await api(`/api/courses/${course}/note/mine?id=${encodeURIComponent(n.id)}`, { method: "PUT", body: JSON.stringify({ text: ta.value }) });
            n.my_notes = ta.value; d.querySelector(".saved").textContent = "saved ✓"; } catch (err) { d.querySelector(".saved").textContent = "not saved"; }
        }, 700);
      };
      const summarize = async (force) => {
        const breakdown = d.querySelector(".breakdown"); breakdown.innerHTML = `<span class="muted">Luna is reading the lesson and writing your breakdown (about 15–30 seconds)…</span>`;
        try { const r = await post(`/api/courses/${course}/note/summarize?id=${encodeURIComponent(n.id)}${force ? "&force=true" : ""}`);
          n.summary = r.summary; renderMd(breakdown, r.summary); if (typeof loadSpend === "function") loadSpend(); }
        catch (err) { breakdown.innerHTML = `<span class="err">${esc(err.message)}</span>`; }
      };
      d.querySelector(".do-sum")?.addEventListener("click", () => summarize(false));
      d.querySelector(".resum")?.addEventListener("click", (e) => { e.preventDefault(); summarize(true); });
      d.querySelector(".show-fullnotes").onclick = async (e) => {  // detailed version: written on first open, then cached
        const box = d.querySelector(".fullnotes");
        if (!box.hidden) { box.hidden = true; e.target.textContent = "Full notes ▸"; return; }
        box.hidden = false; e.target.textContent = "Full notes ▾";
        box.innerHTML = `<span class="muted">${n.has_full ? "loading…" : "Luna is writing the detailed section-by-section notes (about 20–40 seconds)…"}</span>`;
        try { const r = await post(`/api/courses/${course}/note/summarize?id=${encodeURIComponent(n.id)}&full=true`);
          n.has_full = true; renderMd(box, r.summary); if (!r.cached && typeof loadSpend === "function") loadSpend(); }
        catch (err) { box.innerHTML = `<span class="err">${esc(err.message)}</span>`; }
      };
      d.querySelector(".show-full").onclick = async (e) => {
        const full = d.querySelector(".full");
        if (!full.hidden) { full.hidden = true; e.target.textContent = "Show original text"; return; }
        full.textContent = "loading…"; full.hidden = false; e.target.textContent = "Hide original text";
        try { full.textContent = (await api(`/api/courses/${course}/note?id=${encodeURIComponent(n.id)}`)).text; } catch (err) { full.textContent = err.message; }
      };
      d.querySelector(".delete-lesson")?.addEventListener("click", async () => {
        if (!confirm(`Delete “${n.title}” and its breakdown and practice questions? You can save the page again with the extension.`)) return;
        clearTimeout(t);
        const button = d.querySelector(".delete-lesson"); button.disabled = true;
        try {
          await api(`/api/courses/${course}/note?id=${encodeURIComponent(n.id)}`, { method: "DELETE", headers: { "X-Study-Buddy": "1" } });
          if (course !== state.course) return;
          W.practice.delete(practiceKey(n));
          if (W.test?.note.id === n.id) { W.test = null; renderTest(); }
          await Promise.all([loadNotes(), loadTests(), loadGuide()]);
          if (typeof loadCourses === "function") loadCourses();
          toast("Lesson deleted. Open it in the extension to add it again.");
        } catch (err) { button.disabled = false; toast(err.message, "err"); }
      });
      list.appendChild(d);
      d.addEventListener("toggle", () => { if (d.open) ensurePractice(n); });
      if (d.open) ensurePractice(n);
    }
  }
  $("#notesFilter").oninput = (e) => { W.filter = e.target.value.trim(); renderNotes(); };

  function openNote(id) {
    showTab("notes");
    const d = [...document.querySelectorAll("#notesList details.note")].find((x) => x.dataset.id === id);
    if (!d) return;
    d.open = true; d.scrollIntoView({ block: "start", behavior: "smooth" });
    d.classList.add("flash"); setTimeout(() => d.classList.remove("flash"), 1500);
  }

  // "Now reading" card (page synced by the extension)
  let lastPage = null;
  window.addEventListener("sb:page", (e) => {
    const m = e.detail, previousNote = lastPage?.note_id; lastPage = m;
    const hs = m.headings || [];
    $("#pageHeadings").innerHTML = !m.active ? "" : hs.length
      ? `<div class="muted small">Captured ${hs.length} section${hs.length === 1 ? "" : "s"}:</div>` + hs.map((h) => `<div>✓ ${esc(h)}</div>`).join("")
      : `<div class="muted small">No section headings found on this page${m.chars < 800 ? " — only a little text came through. Scroll the lesson or click Sync now in the extension." : "."}</div>`;
    $("#openPageNote").hidden = !m.note_id;
    $("#savePage").hidden = !!m.activity;
    $("#savePage").textContent = m.note_id ? "Update lesson" : "Save & study";
    if (m.note_id && m.note_id !== previousNote) {
      loadNotes().then(() => { if (!W.notes.find((n) => n.id === m.note_id)?.summary) watchSummary(m.note_id); });
    }
  });
  $("#openPageNote").onclick = () => lastPage?.note_id && openNote(lastPage.note_id);
  $("#savePage").onclick = async () => {
    try {
      const r = await post("/api/page/save", { course: state.course });
      if (!r.saved) { toast("Lab and activity pages stay available to your tutor without a lesson note."); return; }
      toast("Lesson saved — preparing its breakdown and test…");
      if (typeof loadCourses === "function") loadCourses();
      const id = r.saved.split("/").slice(1).join("/");
      await loadNotes(); openNote(id); watchSummary(id);
    } catch (err) { note(err.message, "err"); }
  };
  function watchSummary(id) { // the server summarizes new pages in the background; show it when it lands
    clearInterval(W.summaryWatch); let tries = 0;
    W.summaryWatch = setInterval(async () => {
      tries++;
      await loadNotes();
      if (W.notes.find((n) => n.id === id)?.summary || tries > 30) { clearInterval(W.summaryWatch); if (typeof loadSpend === "function") loadSpend(); }
    }, 3000);
  }

  // ---------- course summary tab ----------
  async function loadGuide() {
    if (!state.course) return;
    const course = state.course;
    let g; try { g = await api(`/api/courses/${course}/guide`); } catch { return; }
    if (course !== state.course) return;
    if (g.markdown) { renderMd($("#guide"), g.markdown); $("#guideAge").textContent = `updated ${ago(g.updated_at)}`; $("#buildGuide").textContent = "Update study guide"; }
    else {
      $("#guide").innerHTML = `<div class="empty">Your study guide pulls together every note, your own notes, and what you've covered in chats — organized by section, in plain words, with where you stand. Save a few lesson pages or have a chat, then hit “Build study guide”.</div>`;
      $("#guideAge").textContent = ""; $("#buildGuide").textContent = "Build study guide";
    }
  }
  $("#buildGuide").onclick = async () => {
    const course = state.course;
    const b = $("#buildGuide"); b.disabled = true; $("#guideAge").textContent = "Luna is writing your guide (Flex tier — can take a minute)…";
    try { const g = await post(`/api/courses/${course}/guide`); if (course === state.course) { renderMd($("#guide"), g.markdown); $("#guideAge").textContent = `updated just now · ${money(g.cost)}`; b.textContent = "Update study guide"; } if (typeof loadSpend === "function") loadSpend(); }
    catch (err) { if (course === state.course) { $("#guideAge").textContent = ""; note(err.message, "err"); } }
    b.disabled = false;
  };

  // ---------- course switch ----------
  window.addEventListener("sb:course", () => {
    W.sid = null; $("#warTitle").textContent = "This chat"; renderRecap(null);
    W.practice.clear();
    W.test = null; W.tests = []; W.testPolls = 0; clearTimeout(W.testWatch); renderTest(); renderTests();
    W.filter = ""; $("#notesFilter").value = "";
    loadNotes(); loadTests(); loadGuide();
  });
  if (state.course) { loadNotes(); loadTests(); loadGuide(); }
  window.warroom = { loadNotes, openNote, updateRecap, showTab };
})();
