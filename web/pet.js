// The study pet: a small black robot orb that reacts to the session.
// States: sleep · idle · listening · hearing (you're talking) · thinking · looking · speaking
(() => {
  const el = document.getElementById("pet");
  const statusEl = el.querySelector(".pet-status");
  const nameEl = el.querySelector(".pet-name");
  const orb = el.querySelector(".orb");
  const STATUS = {
    sleep: "sleeping", idle: "ready", listening: "listening…",
    hearing: "hearing you…", thinking: "thinking…", looking: "looking…", speaking: "talking",
  };
  let base = "sleep", transient = null, transientTimer = null, shown = null;
  let mic = null, remote = null, synthetic = 0, level = 0, audioCtx = null;

  function render() {
    let s = transient || base;
    if (s === "listening" && mic && mic.read() > 0.08) s = "hearing";
    if (s !== shown) { el.dataset.state = s; statusEl.textContent = STATUS[s] || ""; shown = s; }
    return s;
  }
  function meter(stream) {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const src = audioCtx.createMediaStreamSource(stream);
      const an = audioCtx.createAnalyser(); an.fftSize = 512; src.connect(an);
      const buf = new Uint8Array(an.fftSize);
      return { read() { an.getByteTimeDomainData(buf); let sum = 0; for (const v of buf) { const x = (v - 128) / 128; sum += x * x; } return Math.min(1, Math.sqrt(sum / buf.length) * 4); } };
    } catch { return null; }
  }
  function loop() {
    const s = render();
    let target = 0;
    if (s === "speaking") target = Math.max(remote ? remote.read() : 0, synthetic);
    else if (s === "hearing") target = mic ? mic.read() : 0;
    else if (s === "thinking" || s === "looking") target = 0.25;
    synthetic *= 0.9;
    level += (target - level) * 0.35;
    el.style.setProperty("--level", level.toFixed(3));
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);

  // blink now and then
  (function blink() {
    if (shown !== "sleep") { el.classList.add("blink"); setTimeout(() => el.classList.remove("blink"), 130); }
    setTimeout(blink, 2500 + Math.random() * 3500);
  })();

  // eyes follow the cursor a little
  document.addEventListener("mousemove", (e) => {
    const r = orb.getBoundingClientRect();
    const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
    const d = Math.max(1, Math.hypot(dx, dy));
    el.style.setProperty("--lx", `${((dx / d) * Math.min(5, d / 40)).toFixed(1)}px`);
    el.style.setProperty("--ly", `${((dy / d) * Math.min(3, d / 60)).toFixed(1)}px`);
  });

  // say hi when clicked
  el.querySelector(".pet-stage").addEventListener("click", () => {
    el.classList.add("happy"); statusEl.textContent = ["hi!", "let's study!", "you've got this", "beep boop"][Math.floor(Math.random() * 4)];
    setTimeout(() => { el.classList.remove("happy"); shown = null; }, 1100);
  });

  // name persists in this browser
  try { const n = localStorage.getItem("petName"); if (n) nameEl.textContent = n; } catch {}
  nameEl.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); nameEl.blur(); } });
  nameEl.addEventListener("blur", () => {
    const n = nameEl.textContent.trim().slice(0, 24) || "Orbi"; nameEl.textContent = n;
    try { localStorage.setItem("petName", n); } catch {}
  });

  window.pet = {
    set(state) { base = state; transient = null; clearTimeout(transientTimer); },
    // a temporary state; falls back to the base state after `ms` without another call
    flash(state, ms = 1200) { transient = state; clearTimeout(transientTimer); transientTimer = setTimeout(() => { transient = null; }, ms); },
    clear() { transient = null; clearTimeout(transientTimer); },
    attachMic(stream) { mic = stream ? meter(stream) : null; audioCtx?.resume?.(); },
    attachRemote(stream) { remote = stream ? meter(stream) : null; audioCtx?.resume?.(); },
    pulse(x = 0.9) { synthetic = Math.max(synthetic, x); },
    get name() { return nameEl.textContent.trim() || "Orbi"; },
  };
})();
