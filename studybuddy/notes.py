"""Course notes (synced pages + class files), breakdowns, Marc's own notes,
per-chat recaps for the war room, and the whole-course study guide."""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from . import brain, page, prompts, spend
from .config import Settings
from .db import Conn

SECTION_RE = re.compile(r"\b(\d{1,2}(?:\.\d{1,2}){1,3})\b")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:12]


def section_of(title: str) -> str:
    m = SECTION_RE.search(title or "")
    return m.group(1) if m else ""


def _section_key(sec: str) -> tuple:
    return tuple(int(x) for x in sec.split(".")) if sec else (999,)


# ---------------- listing & text ----------------

def _page_header(path: Path) -> tuple[str, str]:
    """(title, source_url) from a saved page's markdown header."""
    title, url = path.stem, ""
    try:
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i == 0 and line.startswith("# "):
                    title = line[2:].strip()
                elif line.startswith("Source: "):
                    url = line[8:].strip()
                if i > 6:
                    break
    except OSError:
        pass
    return title, url


def list_notes(conn: Conn, courses_dir: Path, course: str) -> list[dict]:
    rows = conn.execute("SELECT path, kind, indexed_at FROM files WHERE course=?", (course,)).fetchall()
    extra = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, summary, summary_at, full_summary, my_notes, notes_at FROM notes WHERE course=?", (course,))}
    out = []
    for r in rows:
        rel = r["path"]  # relative to course root, e.g. material/pages/x.md
        is_page = "/pages/" in f"/{rel}"
        title, url = _page_header(courses_dir / course / rel) if is_page else (Path(rel).stem.replace("_", " "), "")
        if is_page:
            try:
                with (courses_dir / course / rel).open(encoding="utf-8", errors="replace") as f:
                    sample = f.read(3000)
            except OSError:
                sample = ""
            if page.is_activity_content(title, url, sample):
                continue
        e = extra.get(rel, {})
        out.append({"id": rel, "title": title, "section": section_of(title), "kind": "page" if is_page else r["kind"],
                    "source_url": url, "summary": e.get("summary"), "summary_at": e.get("summary_at"),
                    "has_full": bool(e.get("full_summary")),
                    "my_notes": e.get("my_notes") or "", "notes_at": e.get("notes_at"), "updated": r["indexed_at"]})
    out.sort(key=lambda n: (_section_key(n["section"]), n["kind"] != "page", n["title"].lower()))
    return out


def note_text(conn: Conn, courses_dir: Path, course: str, note_id: str) -> str:
    path = (courses_dir / course / note_id).resolve()
    if not path.is_relative_to((courses_dir / course).resolve()):
        raise ValueError("bad note id")
    if path.suffix.lower() in (".md", ".txt") and path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    rows = conn.execute("SELECT locator, text FROM chunks WHERE course=? AND path=? ORDER BY id", (course, note_id))
    return "\n\n".join(f"[{r['locator']}]\n{r['text']}" if r["locator"] else r["text"] for r in rows)


def set_my_notes(conn: Conn, course: str, note_id: str, text: str) -> dict:
    conn.execute("INSERT INTO notes(course, id, my_notes, notes_at) VALUES (?,?,?,?) "
                 "ON CONFLICT(course, id) DO UPDATE SET my_notes=excluded.my_notes, notes_at=excluded.notes_at",
                 (course, note_id, text, _now()))
    conn.commit()
    return {"ok": True, "notes_at": _now()}


# ---------------- breakdowns (the "digest" of each lesson) ----------------




def _covered(heading: str, md: str) -> bool:
    words = [w for w in re.findall(r"[a-z0-9+]+", heading.lower()) if len(w) > 3 or w.endswith("+")]
    if not words:
        return True
    low = md.lower()
    return sum(w in low for w in words) >= max(1, round(len(words) * 0.6))


def _insert_sections(md: str, extra: str) -> str:
    """Put missing ### sections at the end of 'Section by section' (before '## Key terms')."""
    m = re.search(r"^## Key terms", md, re.M)
    return (md[:m.start()] + extra.strip() + "\n\n" + md[m.start():]) if m else md + "\n\n" + extra.strip()


SHORT_VERSION = "short-1"  # bump when SHORT_BREAKDOWN_PROMPT changes so cached breakdowns are rewritten
MAX_WORDS = 350            # over this, one cheap trim pass


def word_count(md: str) -> int:
    """Words a reader sees; markdown table pipes and dashes don't count."""
    return len(re.findall(r"[^\W_][\w'’-]*", md))


def summarize(conn: Conn, s: Settings, courses_dir: Path, course: str, note_id: str,
              course_name: str, about_me: str, force: bool = False, lock=None, full: bool = False) -> dict:
    """Short breakdown of a note (default), or with full=True the detailed section-by-section
    "full notes", checked so no lesson section is skipped."""
    col = "full_summary" if full else "summary"
    with lock or nullcontext():
        text = note_text(conn, courses_dir, course, note_id)
        h = _sha(text) if full else _sha(SHORT_VERSION + text)
        row = conn.execute(f"SELECT {col} AS md, {col}_hash AS h FROM notes WHERE course=? AND id=?", (course, note_id)).fetchone()
        if row and row["md"] and row["h"] == h and not force:
            return {"summary": row["md"], "cached": True, "cost": 0.0, "words": word_count(row["md"])}
    body = re.sub(r"\A# .*\n(?:\n)?(?:(?:Source|Section|Saved): .*\n)*", "", text).strip()  # drop our file header
    if len(body) < 150:
        raise ValueError("Not enough lesson text to break down. Re-sync the page with the extension and save again.")
    title = text.splitlines()[0][2:].strip() if text.startswith("# ") else Path(note_id).stem.replace("_", " ")
    outline = [x for x in re.findall(r"^#{2,3} (.+)$", body, re.M)]
    usage_total: dict = {"input_tokens": 0, "output_tokens": 0, "input_tokens_details": {"cached_tokens": 0}}

    def call(prompt: str, max_out: int, task: str) -> str:
        text, usage = brain.response_text(s, prompt, task, max_output_tokens=max_out)
        spend.merge_usage(usage_total, usage)
        return text

    extra_out: dict = {}
    if full:
        summary = call(prompts.BREAKDOWN_PROMPT.format(
            course=course_name, about_me=about_me or "(not given)", title=title, text=body[:60_000],
            outline="\n".join(f"- {x}" for x in outline) or "- (no headings found — organize by topic yourself)"), 9000, "breakdown")
        missing = [x for x in outline if not _covered(x, summary)]
        if missing:  # one repair pass for skipped sections
            extra = call(prompts.FIX_PROMPT.format(title=title, missing="; ".join(missing), text=body[:60_000]), 4000, "breakdown_repair")
            summary = _insert_sections(summary, extra)
            missing = [x for x in outline if not _covered(x, summary)]
        extra_out = {"sections": outline, "missing": missing}
    else:
        summary = call(prompts.SHORT_BREAKDOWN_PROMPT.format(
            course=course_name, about_me=about_me or "(not given)", title=title, text=body[:60_000]), 3000, "breakdown")
        words = word_count(summary)
        if words > MAX_WORDS:  # guardrail: one cheap trim of the draft alone (no lesson text)
            trimmed = call(prompts.TRIM_PROMPT.format(words=words, draft=summary), 1500, "breakdown_trim").strip()
            if trimmed and word_count(trimmed) < words:
                summary = trimmed
    with lock or nullcontext():
        conn.execute(f"INSERT INTO notes(course, id, {col}, {col}_hash, summary_at) VALUES (?,?,?,?,?) "
                     f"ON CONFLICT(course, id) DO UPDATE SET {col}=excluded.{col}, "
                     f"{col}_hash=excluded.{col}_hash, summary_at=excluded.summary_at",
                     (course, note_id, summary, h, _now()))
        conn.commit()
        cost = spend.charge_background(conn, s, course, "breakdown_full" if full else "breakdown", usage_total)
    return {"summary": summary, "cached": False, "cost": cost, "words": word_count(summary), **extra_out}


# ---------------- per-chat recap (war room) ----------------



def _transcript_text(transcript: list[dict], limit: int = 30_000) -> str:
    lines = []
    for m in transcript:
        t = (m.get("text") or "").strip()
        if t:
            lines.append(f"{'Marc' if m.get('role') == 'you' else 'Tutor' if m.get('role') == 'tutor' else 'Note'}: {t}")
    text = "\n".join(lines)
    return text[-limit:]


def _board_text(boards: list[dict] | None, limit: int = 12_000) -> str:
    lines = []
    for board in boards or []:
        title = str(board.get("title") or "").strip()
        markdown = str(board.get("markdown") or "").strip()
        if title or markdown:
            lines.append(f"Board: {title}\n{markdown}")
    return "\n\n".join(lines)[-limit:]


def build_recap(conn: Conn, s: Settings, sid: str, transcript: list[dict], course_name: str = "", lock=None,
                boards: list[dict] | None = None) -> dict:
    text = _transcript_text(transcript)
    board_text = _board_text(boards)
    if len(text) + len(board_text) < 40:
        raise ValueError("Not enough conversation yet for a recap.")
    with lock or nullcontext():
        row = conn.execute("SELECT course FROM sessions WHERE id=?", (sid,)).fetchone()
    if row is None:
        raise KeyError(sid)
    raw, usage = brain.response_text(s, prompts.RECAP_PROMPT.format(
        course=f" in {course_name}" if course_name else "", transcript=text,
        boards=board_text or "(Nothing was put on the board.)"), "recap", max_output_tokens=2000)
    try:
        recap = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except ValueError:
        recap = {"covered": [], "next_up": raw[:400]}
    recap["updated_at"] = _now()
    with lock or nullcontext():
        conn.execute("UPDATE sessions SET recap=? WHERE id=?", (json.dumps(recap), sid))
        conn.commit()
        recap["cost"] = spend.charge_background(conn, s, row["course"], "recap", usage)
    return recap


def get_recap(conn: Conn, sid: str) -> dict | None:
    row = conn.execute("SELECT recap FROM sessions WHERE id=?", (sid,)).fetchone()
    return json.loads(row["recap"]) if row and row["recap"] else None


# ---------------- whole-course study guide ----------------



def build_guide(conn: Conn, s: Settings, courses_dir: Path, course: str, course_name: str, lock=None) -> dict:
    parts = []
    with lock or nullcontext():
        full = {r["id"]: r["full_summary"] for r in conn.execute(
            "SELECT id, full_summary FROM notes WHERE course=? AND full_summary IS NOT NULL", (course,))}
        for n in list_notes(conn, courses_dir, course):
            body = full.get(n["id"]) or n["summary"] or note_text(conn, courses_dir, course, n["id"])[:2500]
            parts.append(f"### NOTE: {n['title']}\n{body}" + (f"\nMARC'S OWN NOTES: {n['my_notes']}" if n["my_notes"] else ""))
        recaps = conn.execute("SELECT started_at, recap FROM sessions WHERE course=? AND recap IS NOT NULL "
                              "ORDER BY started_at", (course,)).fetchall()
        prog = conn.execute("SELECT name, mastery, attempts FROM concepts WHERE course=? AND attempts>0", (course,)).fetchall()
    for r in recaps:
        rc = json.loads(r["recap"])
        parts.append(f"### CHAT RECAP ({r['started_at'][:10]}): covered={rc.get('covered')}; "
                     f"weak_spots={rc.get('weak_spots')}; clicked={rc.get('clicked')}")
    if prog:
        parts.append("### PROGRESS: " + "; ".join(f"{p['name']} {round(p['mastery'] * 100)}%" for p in prog))
    material = "\n\n".join(parts)
    if len(material) < 200:
        raise ValueError("Save a few lesson pages or have a chat first — there's nothing to build a guide from yet.")
    md, usage = brain.response_text(s, prompts.GUIDE_PROMPT.format(course=course_name, material=material[:300_000]),
                                    "study_guide", flex=True, max_output_tokens=12000)
    with lock or nullcontext():
        conn.execute("INSERT INTO guides(course, markdown, updated_at) VALUES (?,?,?) ON CONFLICT(course) "
                     "DO UPDATE SET markdown=excluded.markdown, updated_at=excluded.updated_at", (course, md, _now()))
        conn.commit()
        cost = spend.charge_background(conn, s, course, "study_guide", usage)
    return {"markdown": md, "updated_at": _now(), "cost": cost}


def get_guide(conn: Conn, course: str) -> dict | None:
    row = conn.execute("SELECT markdown, updated_at FROM guides WHERE course=?", (course,)).fetchone()
    return dict(row) if row else None
