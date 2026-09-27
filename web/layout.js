// Adjustable course list, lesson pane, and chat widths.
(() => {
  const app = document.querySelector("#app");
  const sidebar = document.querySelector("#sidebar");
  const chat = document.querySelector("main");
  const toggles = { sidebar: document.querySelector("#toggleSidebar"), chat: document.querySelector("#toggleChat") };
  const handles = {
    sidebar: document.querySelector("#resizeSidebar"),
    chat: document.querySelector("#resizeChat"),
  };
  const key = "studyBuddyPaneWidths";
  const collapseKey = "studyBuddyCollapsedPanes";
  const minimum = { sidebar: 210, lesson: 320, chat: 360 };
  const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
  const width = () => app.getBoundingClientRect().width;
  const current = () => ({
    sidebar: sidebar.getBoundingClientRect().width,
    chat: chat.getBoundingClientRect().width,
  });
  let preferred = { sidebar: 270, chat: null };
  let collapsed = { sidebar: false, chat: false };
  try {
    const saved = JSON.parse(localStorage.getItem(key) || "null");
    if (Number.isFinite(saved?.sidebar) && Number.isFinite(saved?.chat)) preferred = saved;
    const hidden = JSON.parse(localStorage.getItem(collapseKey) || "null");
    if (hidden) collapsed = { sidebar: !!hidden.sidebar, chat: !!hidden.chat };
  } catch {}

  function draw() {
    app.classList.toggle("sidebar-collapsed", collapsed.sidebar);
    app.classList.toggle("chat-collapsed", collapsed.chat);
    toggles.sidebar.textContent = collapsed.sidebar ? "Courses ▶" : "◀ Courses";
    toggles.chat.textContent = collapsed.chat ? "◀ Chat" : "Chat ▶";
    for (const pane of ["sidebar", "chat"]) {
      toggles[pane].setAttribute("aria-expanded", String(!collapsed[pane]));
      toggles[pane].title = `${collapsed[pane] ? "Show" : "Hide"} ${pane === "sidebar" ? "courses" : "chat"}`;
    }
    if (width() <= 1000) return;
    const side = clamp(preferred.sidebar, minimum.sidebar, width() - minimum.lesson - (collapsed.chat ? 0 : minimum.chat));
    const right = clamp(preferred.chat ?? width() * 0.4, minimum.chat, width() - (collapsed.sidebar ? 0 : side) - minimum.lesson);
    app.style.setProperty("--sidebar-width", `${Math.round(side)}px`);
    app.style.setProperty("--chat-width", `${Math.round(right)}px`);
    handles.sidebar.setAttribute("aria-valuemin", minimum.sidebar);
    handles.sidebar.setAttribute("aria-valuemax", Math.round(width() - right - minimum.lesson));
    handles.sidebar.setAttribute("aria-valuenow", Math.round(side));
    handles.chat.setAttribute("aria-valuemin", minimum.chat);
    handles.chat.setAttribute("aria-valuemax", Math.round(width() - side - minimum.lesson));
    handles.chat.setAttribute("aria-valuenow", Math.round(right));
  }

  function save() {
    try { localStorage.setItem(key, JSON.stringify(preferred)); } catch {}
  }

  for (const pane of ["sidebar", "chat"]) {
    toggles[pane].addEventListener("click", () => {
      collapsed[pane] = !collapsed[pane];
      try { localStorage.setItem(collapseKey, JSON.stringify(collapsed)); } catch {}
      draw();
    });
  }

  for (const [pane, handle] of Object.entries(handles)) {
    let fixedOther = null;
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || width() <= 1000) return;
      event.preventDefault();
      const visible = current();
      if (!collapsed.sidebar) preferred.sidebar = visible.sidebar;
      if (!collapsed.chat) preferred.chat = visible.chat;
      fixedOther = pane === "sidebar" ? (collapsed.chat ? 0 : preferred.chat) : (collapsed.sidebar ? 0 : preferred.sidebar);
      handle.setPointerCapture(event.pointerId);
      handle.classList.add("dragging");
      document.body.classList.add("resizing-panes");
    });
    handle.addEventListener("pointermove", (event) => {
      if (!handle.hasPointerCapture(event.pointerId)) return;
      const x = event.clientX - app.getBoundingClientRect().left;
      if (pane === "sidebar") {
        preferred.sidebar = clamp(x, minimum.sidebar, width() - fixedOther - minimum.lesson);
      } else {
        preferred.chat = clamp(width() - x, minimum.chat, width() - fixedOther - minimum.lesson);
      }
      draw();
    });
    const finish = (event) => {
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      handle.classList.remove("dragging");
      document.body.classList.remove("resizing-panes");
      fixedOther = null;
      save();
    };
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
    handle.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const amount = (event.shiftKey ? 80 : 24) * (event.key === "ArrowRight" ? 1 : -1);
      const visible = current();
      if (!collapsed.sidebar) preferred.sidebar = visible.sidebar;
      if (!collapsed.chat) preferred.chat = visible.chat;
      if (pane === "sidebar") preferred.sidebar += amount;
      else preferred.chat -= amount;
      draw(); save();
    });
    handle.addEventListener("dblclick", () => {
      preferred = { sidebar: 270, chat: null };
      draw();
      try { localStorage.removeItem(key); } catch {}
    });
  }
  window.addEventListener("resize", draw);
  draw();
})();
