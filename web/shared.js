// Small UI helpers shared by the chat and war room.
const $ = (selector) => document.querySelector(selector);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status} ${r.statusText}`);
  return body;
};
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
const money = (x) => (x < 0.01 && x > 0 ? `$${x.toFixed(4)}` : `$${(x || 0).toFixed(2)}`);
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const emit = (name, detail = {}) => window.dispatchEvent(new CustomEvent(name, { detail }));

// Markdown can contain raw HTML. Only allow the formatting needed by the board and notes.
function renderMd(el, markdown) {
  if (!window.marked) { el.textContent = markdown || ""; return; }
  const template = document.createElement("template");
  template.innerHTML = marked.parse(markdown || "");
  const allowed = new Set(["A", "B", "BLOCKQUOTE", "BR", "CODE", "DEL", "DIV", "EM", "H1", "H2", "H3",
    "H4", "H5", "H6", "HR", "I", "LI", "OL", "P", "PRE", "S", "SPAN", "STRONG", "TABLE", "TBODY",
    "TD", "TH", "THEAD", "TR", "UL"]);
  for (const node of [...template.content.querySelectorAll("*")]) {
    if (!allowed.has(node.tagName)) { node.remove(); continue; }
    for (const attr of [...node.attributes]) {
      if (node.tagName === "A" && attr.name === "href" && /^https?:\/\//i.test(attr.value)) continue;
      if (node.tagName === "CODE" && attr.name === "class" && /^language-[\w-]+$/.test(attr.value)) continue;
      node.removeAttribute(attr.name);
    }
    if (node.tagName === "A") { node.target = "_blank"; node.rel = "noopener noreferrer"; }
  }
  el.replaceChildren(template.content);
  if (window.renderMathInElement) renderMathInElement(el, { delimiters: [
    { left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false },
    { left: "\\(", right: "\\)", display: false }, { left: "\\[", right: "\\]", display: true }] });
  if (window.hljs) el.querySelectorAll("pre code").forEach((c) => hljs.highlightElement(c));
}
