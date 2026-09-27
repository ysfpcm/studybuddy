"""Local web server: serves the UI and brokers GPT-Live-1 / GPT-6 Luna. Binds to localhost only."""
from __future__ import annotations

import json
import io
import logging
import threading
import wave
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import brain, ingest, notes, page, practice, progress, prompts, spend, tools
from .config import ROOT, settings
from .db import connect

log = logging.getLogger("studybuddy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ABOUT_ME_TEMPLATE = """# About me (the tutor uses this to pick analogies that click)
Work / background:
Hobbies & things I know well:
How I learn best:
Classes this term:
"""

settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.courses_dir.mkdir(parents=True, exist_ok=True)
if not settings.profile_path.exists():
    settings.profile_path.write_text(ABOUT_ME_TEMPLATE, encoding="utf-8")

conn = connect(settings.db_path)
db_lock = threading.RLock()
chats: dict[str, brain.Chat] = {}



@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_index_all, daemon=True).start()  # index course folders in the background
    yield




def _course(slug: str) -> dict:
    try:
        return ingest.course_meta(settings.courses_dir, slug)
    except KeyError:
        raise HTTPException(404, f"No course folder named '{slug}' in {settings.courses_dir}")


def _about_me() -> str:
    text = settings.profile_path.read_text(encoding="utf-8")
    return "" if text.strip() == ABOUT_ME_TEMPLATE.strip() else text


def _index_all() -> None:
    for c in ingest.list_courses(settings.courses_dir):
        with db_lock:
            stats = ingest.index_course(conn, settings.courses_dir, c["slug"])
        log.info("indexed %s: %s", c["slug"], stats)
        _backfill_tests(c["slug"], c["name"])


def _backfill_tests(course: str, course_name: str) -> None:
    with db_lock:
        pending = [n for n in practice.test_status(conn, settings.courses_dir, course) if not n["ready"]]
    for n in pending:
        try:
            practice.ensure_test(conn, settings, settings.courses_dir, course, n["id"], course_name, lock=db_lock)
        except Exception as e:  # noqa: BLE001 - leave other lesson tests running
            log.warning("auto-test failed for %s/%s: %s", course, n["id"], e)


app = FastAPI(title="Study Buddy", lifespan=lifespan)


# ---------- status & courses ----------

@app.get("/api/status")
def status():
    return {"api_key_set": bool(settings.api_key), "live_model": settings.live_model,
            "brain_model": settings.brain_model, "delegation_mode": settings.delegation_mode,
            "max_session_minutes": settings.max_session_minutes, "idle_end_seconds": settings.idle_end_seconds,
            "price_live_per_min": settings.price_live_per_min, "vision_provider": settings.vision_provider,
            "monthly_budget": settings.monthly_budget, "modes":
                {k: v["label"] for k, v in prompts.MODES.items()},
            "courses_dir": str(settings.courses_dir)}


@app.get("/api/courses")
def courses():
    out = []
    with db_lock:
        for c in ingest.list_courses(settings.courses_dir):
            files = conn.execute("SELECT COUNT(*) FROM files WHERE course=?", (c["slug"],)).fetchone()[0]
            concepts = conn.execute("SELECT COUNT(*), AVG(mastery) FROM concepts WHERE course=?",
                                    (c["slug"],)).fetchone()
            out.append({**c, "files": files, "concepts": concepts[0],
                        "avg_mastery": round(concepts[1] or 0, 2)})
    return out


@app.post("/api/courses/{slug}/index")
def reindex(slug: str):
    _course(slug)
    with db_lock:
        return ingest.index_course(conn, settings.courses_dir, slug)


@app.post("/api/courses/{slug}/concepts/build")
def build_concepts(slug: str):
    _course(slug)
    with db_lock:
        material = ingest.course_text(conn, slug)
    if not material:
        raise HTTPException(400, "No indexed material yet. Add files to the course's material folder and re-index.")
    try:
        concepts, usage = brain.extract_concepts(settings, material)
    except brain.OpenAIError as e:
        raise HTTPException(502, str(e))
    with db_lock:
        for c in concepts:
            progress.upsert_concept(conn, slug, c["name"], c.get("unit", ""), c.get("objective", ""))
        conn.commit()
        sid = spend.start_session(conn, slug, "concept_map", "background")
        spend.add_brain_usage(conn, sid, usage)
        cost = spend.close_session(conn, settings, sid)["cost_total"]
    threading.Thread(target=_backfill_tests, args=(slug, _course(slug)["name"]), daemon=True).start()
    return {"added_or_updated": len(concepts), "cost": cost}


@app.get("/api/courses/{slug}/progress")
def course_progress(slug: str):
    _course(slug)
    with db_lock:
        return {"concepts": progress.overview(conn, slug), "focus": progress.study_focus(conn, slug)}


@app.get("/api/about_me")
def get_about_me():
    return {"text": settings.profile_path.read_text(encoding="utf-8")}


@app.put("/api/about_me")
def put_about_me(text: str = Body(..., embed=True)):
    settings.profile_path.write_text(text, encoding="utf-8")
    return {"ok": True}


# ---------- sessions & spend ----------

def _transcript_recap(sid: str, turns: int = 20) -> str:
    row = conn.execute("SELECT transcript_file FROM sessions WHERE id=?", (sid,)).fetchone()
    t = _load_transcript(row["transcript_file"] if row else None)[-turns:]
    return "\n".join(f"{'Marc' if m.get('role') == 'you' else 'Tutor'}: {m.get('text', '').strip()}" for m in t)


class SessionStart(BaseModel):
    course: str
    mode: str = "guided"
    channel: str = "text"  # text | economy
    resume_sid: str | None = None


@app.post("/api/sessions/start")
def session_start(req: SessionStart):
    """Economy-voice and text sessions: cheap, server-side Luna loop."""
    course = _course(req.course)
    instructions = prompts.brain_instructions(course, req.mode, _about_me())
    with db_lock:
        recap = _transcript_recap(req.resume_sid) if req.resume_sid else ""
        sid = spend.start_session(conn, req.course, req.mode, req.channel)
    if recap:
        instructions += prompts.RESUME_TEMPLATE.format(recap=recap)
    chat_obj = brain.Chat(course=req.course, mode=req.mode, sid=sid, instructions=instructions)
    chats[chat_obj.id] = chat_obj
    return {"sid": sid, "chat_id": chat_obj.id, "resumed": bool(recap)}


def _load_transcript(fname: str | None) -> list[dict]:
    if not fname:
        return []
    path = settings.data_dir / "sessions" / fname
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("transcript", [])
    except (OSError, ValueError):
        return []


@app.get("/api/courses/{slug}/sessions")
def course_sessions(slug: str, limit: int = 50):
    """This course's chat history, newest first."""
    _course(slug)
    with db_lock:
        rows = conn.execute(
            "SELECT id, mode, channel, started_at, ended_at, voice_seconds, cost_total, transcript_file, recap "
            "FROM sessions WHERE course=? AND channel != 'background' AND transcript_file IS NOT NULL "
            "ORDER BY started_at DESC LIMIT ?", (slug, limit)).fetchall()
    out = []
    for r in rows:
        t = _load_transcript(r["transcript_file"])
        first = next((m.get("text", "").strip() for m in t if m.get("role") == "you" and m.get("text", "").strip()
                      and not m["text"].startswith("[")), "")
        out.append({**{k: r[k] for k in ("id", "mode", "channel", "started_at", "ended_at", "voice_seconds", "cost_total")},
                    "title": (json.loads(r["recap"]).get("title") if r["recap"] else None)
                             or ((first[:70] + "…") if len(first) > 70 else (first or prompts.MODES.get(r["mode"], {}).get("label", "Session"))),
                    "turns": len(t)})
    return out


@app.get("/api/sessions/{sid}/transcript")
def session_transcript(sid: str):
    with db_lock:
        row = conn.execute("SELECT course, mode, channel, started_at, cost_total, transcript_file FROM sessions WHERE id=?",
                           (sid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no session {sid}")
    boards = []
    if row["transcript_file"]:
        try:
            boards = json.loads((settings.data_dir / "sessions" / row["transcript_file"]).read_text(encoding="utf-8")).get("boards", [])
        except (OSError, ValueError):
            pass
    with db_lock:
        recap = notes.get_recap(conn, sid)
    return {**{k: row[k] for k in ("course", "mode", "channel", "started_at", "cost_total")},
            "transcript": _load_transcript(row["transcript_file"]), "boards": boards, "recap": recap}


@app.delete("/api/sessions/{sid}")
def session_delete(sid: str, request: Request):
    """Remove a chat from history: deletes its transcript/boards file and recap.
    The spend row stays (cost already happened) so monthly totals remain accurate."""
    _require_extension(request)  # custom header => cross-site pages can't trigger deletes
    with db_lock:
        row = conn.execute("SELECT transcript_file FROM sessions WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise HTTPException(404, f"no session {sid}")
        if row["transcript_file"]:
            path = (settings.data_dir / "sessions" / row["transcript_file"]).resolve()
            if path.parent == (settings.data_dir / "sessions").resolve():
                path.unlink(missing_ok=True)
        conn.execute("UPDATE sessions SET transcript_file=NULL, recap=NULL WHERE id=?", (sid,))
        conn.commit()
    return {"ok": True}


class SessionClose(BaseModel):
    measured_seconds: float = 0
    boards: list[dict] = []            # what the tutor put on the board during this chat
    client_usage: dict | None = None   # Luna usage the browser saw (delegation mode)
    raw_usage: dict | None = None      # session.closed usage payload from GPT-Live
    transcript: list[dict] = []


@app.post("/api/sessions/{sid}/close")
def session_close(sid: str, req: SessionClose):
    fname = None
    if req.transcript or req.boards:
        d = settings.data_dir / "sessions"
        d.mkdir(exist_ok=True)
        fname = f"{sid}.json"
        (d / fname).write_text(json.dumps(req.model_dump(), indent=2), encoding="utf-8")
    try:
        with db_lock:
            return spend.close_session(conn, settings, sid, req.measured_seconds, req.client_usage,
                                       req.raw_usage, fname)
    except KeyError:
        raise HTTPException(404, f"no session {sid}")


class SpeechReq(BaseModel):
    sid: str
    text: str


@app.post("/api/tts")
def economy_speech(req: SpeechReq):
    text = req.text.strip()
    if not text or len(text) > 4000:
        raise HTTPException(400, "Speech text must be 1–4000 characters.")
    with db_lock:
        row = conn.execute("SELECT channel, ended_at FROM sessions WHERE id=?", (req.sid,)).fetchone()
    if row is None or row["channel"] != "economy" or row["ended_at"]:
        raise HTTPException(404, "No active Economy session with that ID.")
    try:
        audio = brain.synthesize_speech(settings, text)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            seconds = wav.getnframes() / wav.getframerate()
    except brain.OpenAIError as e:
        raise HTTPException(502, str(e))
    except (wave.Error, EOFError, ZeroDivisionError) as e:
        raise HTTPException(502, f"Speech service returned invalid audio: {e}")
    with db_lock:
        spend.add_tts(conn, settings, req.sid, seconds)
    return Response(audio, media_type="audio/wav")


@app.get("/api/spend")
def get_spend():
    with db_lock:
        return {"month": spend.month_summary(conn, settings), "recent": spend.recent(conn)}


# ---------- the page Marc is studying (from the browser extension) ----------

ui_state: dict = {"course": None}


class UIState(BaseModel):
    course: str | None = None


@app.post("/api/ui/state")
def set_ui_state(req: UIState):
    ui_state["course"] = req.course
    return ui_state


class PagePush(BaseModel):
    url: str
    title: str = ""
    text: str
    selection: str = ""
    section: str = ""           # e.g. "1.1.1", detected on the page by the extension
    section_title: str = ""     # e.g. "Networking Concepts"
    save: bool = False          # also save into the course's notes
    course: str | None = None   # which course to save to (defaults to the one open in the app)


def _require_extension(request: Request) -> None:
    # Custom header => browsers force a CORS preflight for ordinary web pages, which we never
    # approve, so random websites can't inject "page content". The extension isn't subject to CORS.
    if request.headers.get("x-study-buddy") != "1":
        raise HTTPException(403, "missing X-Study-Buddy header")


@app.post("/api/page")
def push_page(req: PagePush, request: Request):
    _require_extension(request)
    info = page.set_page(req.url, req.title, req.text, req.selection, req.section, req.section_title)
    saved = None
    if req.save:
        saved = _save_page(req.course or ui_state["course"])
    return {**info, "saved": saved, "course": req.course or ui_state["course"]}


@app.get("/api/page")
def page_meta():
    m = {**page.meta(), "course": ui_state["course"], "note_id": None}
    if m["active"] and ui_state["course"] and not m.get("activity"):
        p = page.note_path(settings.courses_dir, ui_state["course"])
        if p.exists():
            m["note_id"] = p.relative_to(settings.courses_dir / ui_state["course"]).as_posix()
    return m


@app.delete("/api/page")
def page_clear(request: Request):
    _require_extension(request)
    page.clear()
    return {"active": False}


class PageSave(BaseModel):
    course: str | None = None


@app.post("/api/page/save")
def page_save(req: PageSave):
    saved = _save_page(req.course or ui_state["course"])
    return {"saved": saved, "skipped": "lab_activity" if saved is None else None}


def _save_page(course: str | None) -> str | None:
    if not course:
        raise HTTPException(400, "Open a course in Study Buddy first (or pick one in the extension).")
    _course(course)
    if page.is_activity():
        return None  # keep the live page synced for tutoring, but do not create a lesson note
    try:
        path, replaced = page.save_to_course(settings.courses_dir, course)
    except ValueError as e:
        raise HTTPException(400, str(e))
    root = settings.courses_dir / course
    note_id = path.relative_to(root).as_posix()
    with db_lock:
        for old in replaced:  # keep Marc's own notes when an older copy of this lesson is replaced
            old_id = old.relative_to(root).as_posix()
            mine = conn.execute("SELECT my_notes FROM notes WHERE course=? AND id=?", (course, old_id)).fetchone()
            if mine and mine["my_notes"]:
                notes.set_my_notes(conn, course, note_id, mine["my_notes"])
            conn.execute("DELETE FROM notes WHERE course=? AND id=?", (course, old_id))
        conn.commit()
        ingest.index_course(conn, settings.courses_dir, course)
    threading.Thread(target=_summarize_quietly, args=(course, note_id), daemon=True).start()
    return path.relative_to(settings.courses_dir).as_posix()


def _summarize_quietly(course: str, note_id: str) -> None:
    """Auto breakdown and lesson test for a freshly saved page."""
    try:
        meta = _course(course)
        notes.summarize(conn, settings, settings.courses_dir, course, note_id, meta["name"], _about_me(), lock=db_lock)
    except Exception as e:  # noqa: BLE001 - background best effort
        log.warning("auto-summary failed for %s/%s: %s", course, note_id, e)
    try:
        meta = _course(course)
        practice.ensure_test(conn, settings, settings.courses_dir, course, note_id, meta["name"], lock=db_lock)
    except Exception as e:  # noqa: BLE001 - breakdown and test can succeed independently
        log.warning("auto-test failed for %s/%s: %s", course, note_id, e)


# ---------- course notes, summaries, study guide ----------

@app.get("/api/courses/{slug}/notes")
def course_notes(slug: str):
    _course(slug)
    with db_lock:
        return notes.list_notes(conn, settings.courses_dir, slug)


@app.get("/api/courses/{slug}/note")
def course_note_text(slug: str, id: str):
    _course(slug)
    try:
        with db_lock:
            return {"text": notes.note_text(conn, settings.courses_dir, slug, id)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/courses/{slug}/note")
def course_note_delete(slug: str, id: str, request: Request):
    _require_extension(request)
    _course(slug)
    root = (settings.courses_dir / slug).resolve()
    path = (root / id).resolve()
    pages = root / "material" / "pages"
    if not path.is_relative_to(pages) or path.suffix.lower() != ".md":
        raise HTTPException(400, "Only saved lesson pages can be deleted here.")
    rel = path.relative_to(root).as_posix()
    with db_lock:
        indexed = conn.execute("SELECT 1 FROM files WHERE course=? AND path=?", (slug, rel)).fetchone()
        if not indexed or not path.is_file():
            raise HTTPException(404, "Saved lesson not found.")
        path.unlink()
        conn.execute("DELETE FROM practice_answers WHERE run_id IN "
                     "(SELECT id FROM practice_runs WHERE course=? AND note_id=?)", (slug, rel))
        conn.execute("DELETE FROM practice_runs WHERE course=? AND note_id=?", (slug, rel))
        conn.execute("DELETE FROM practice_sets WHERE course=? AND note_id=?", (slug, rel))
        conn.execute("DELETE FROM notes WHERE course=? AND id=?", (slug, rel))
        conn.execute("DELETE FROM guides WHERE course=?", (slug,))
        ingest.index_course(conn, settings.courses_dir, slug)
    return {"ok": True}


class MyNotes(BaseModel):
    text: str


@app.put("/api/courses/{slug}/note/mine")
def course_note_mine(slug: str, id: str, req: MyNotes):
    _course(slug)
    with db_lock:
        return notes.set_my_notes(conn, slug, id, req.text[:50_000])


@app.post("/api/courses/{slug}/note/summarize")
def course_note_summarize(slug: str, id: str, force: bool = False, full: bool = False):
    meta = _course(slug)
    try:
        return notes.summarize(conn, settings, settings.courses_dir, slug, id, meta["name"], _about_me(), force,
                               lock=db_lock, full=full)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except brain.OpenAIError as e:
        raise HTTPException(502, str(e))


@app.post("/api/courses/{slug}/note/practice")
def course_note_practice(slug: str, id: str, force: bool = False):
    meta = _course(slug)
    try:
        return practice.start(conn, settings, settings.courses_dir, slug, id, meta["name"], force, lock=db_lock)
    except practice.GenerationError as e:
        raise HTTPException(502, str(e))
    except practice.PracticeError as e:
        raise HTTPException(400, str(e))
    except brain.OpenAIError as e:
        raise HTTPException(502, str(e))


@app.get("/api/courses/{slug}/tests")
def course_tests(slug: str):
    _course(slug)
    with db_lock:
        return practice.test_status(conn, settings.courses_dir, slug)


@app.post("/api/courses/{slug}/note/test")
def course_note_test(slug: str, id: str, force: bool = False):
    meta = _course(slug)
    try:
        return practice.start(conn, settings, settings.courses_dir, slug, id, meta["name"],
                              force, lock=db_lock, kind="test")
    except practice.GenerationError as e:
        raise HTTPException(502, str(e))
    except practice.PracticeError as e:
        raise HTTPException(400, str(e))
    except brain.OpenAIError as e:
        raise HTTPException(502, str(e))


class PracticeAnswer(BaseModel):
    run_id: str
    item_id: str
    choice: int | None = None
    rating: str | None = None


@app.post("/api/courses/{slug}/note/practice/answer")
def course_note_practice_answer(slug: str, id: str, req: PracticeAnswer):
    _course(slug)
    try:
        with db_lock:
            return practice.answer(conn, slug, id, req.run_id, req.item_id, req.choice, req.rating)
    except practice.PracticeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/courses/{slug}/guide")
def course_guide(slug: str):
    _course(slug)
    with db_lock:
        return notes.get_guide(conn, slug) or {"markdown": None, "updated_at": None}


@app.post("/api/courses/{slug}/guide")
def course_guide_build(slug: str):
    meta = _course(slug)
    try:
        return notes.build_guide(conn, settings, settings.courses_dir, slug, meta["name"], lock=db_lock)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except brain.OpenAIError as e:
        raise HTTPException(502, str(e))


class RecapReq(BaseModel):
    transcript: list[dict] | None = None   # current transcript (live); omitted = use the saved one
    boards: list[dict] | None = None       # current board (live); omitted = use the saved one


@app.post("/api/sessions/{sid}/recap")
def session_recap(sid: str, req: RecapReq):
    with db_lock:
        row = conn.execute("SELECT course, transcript_file FROM sessions WHERE id=?", (sid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no session {sid}")
    saved = {}
    if row["transcript_file"] and (req.transcript is None or req.boards is None):
        try:
            saved = json.loads((settings.data_dir / "sessions" / row["transcript_file"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    transcript = req.transcript if req.transcript is not None else saved.get("transcript", [])
    boards = req.boards if req.boards is not None else saved.get("boards", [])
    try:
        meta = _course(row["course"])
        return notes.build_recap(conn, settings, sid, transcript, meta["name"], lock=db_lock, boards=boards)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except brain.OpenAIError as e:
        raise HTTPException(502, str(e))


@app.get("/api/sessions/{sid}/recap")
def session_recap_get(sid: str):
    with db_lock:
        return {"recap": notes.get_recap(conn, sid)}


# ---------- eyes ----------

class VisionReq(BaseModel):
    image: str               # data: URL (downscaled JPEG from the browser)
    question: str = ""
    sid: str | None = None
    kind: str = "screen"     # screen (live look) | paste (screenshot pasted into chat)


@app.post("/api/vision/describe")
def vision_describe(req: VisionReq):
    """Turns an image into text context. The image is never written to disk."""
    try:
        text, cost = brain.describe_screen(settings, req.image, req.question, req.kind)
    except Exception as e:  # noqa: BLE001 - surface any provider error
        raise HTTPException(502, f"Couldn't look at the screen: {e}")
    with db_lock:
        spend.add_vision(conn, req.sid, cost)
    return {"description": text, "cost": round(cost, 6)}


# ---------- voice (GPT-Live-1 over WebRTC) ----------

class LiveStart(BaseModel):
    sdp: str
    course: str
    mode: str = "guided"
    resume_sid: str | None = None


@app.post("/api/live/session")
def live_session(req: LiveStart):
    course = _course(req.course)
    with db_lock:
        if spend.over_budget(conn, settings):
            m = spend.month_summary(conn, settings)
            raise HTTPException(402, f"Monthly budget reached (${m['spent']:.2f} of ${m['budget']:.2f}). "
                                     "Use Economy voice or Text, or raise MONTHLY_BUDGET in .env.")
        recap = _transcript_recap(req.resume_sid) if req.resume_sid else ""
    brain_instr = prompts.brain_instructions(course, req.mode, _about_me())
    if recap:
        brain_instr += prompts.RESUME_TEMPLATE.format(recap=recap)
    cfg = brain.live_session_config(settings, prompts.voice_instructions(course), brain_instr)
    try:
        res = brain.create_live_session(settings, req.sdp, cfg)
    except brain.OpenAIError as e:
        raise HTTPException(502, str(e))
    with db_lock:
        sid = spend.start_session(conn, req.course, req.mode, "live")
    chat_obj = brain.Chat(course=req.course, mode=req.mode, instructions=brain_instr, sid=sid)
    chats[chat_obj.id] = chat_obj  # used when DELEGATION_MODE=client
    return {"sdp": res["transport"]["sdp"], "session_id": res.get("session", {}).get("id"),
            "sid": sid, "chat_id": chat_obj.id, "delegation_mode": settings.delegation_mode,
            "max_session_minutes": settings.max_session_minutes, "resumed": bool(recap)}


@app.post("/api/tools/{course}/{name}")
def run_tool(course: str, name: str, args: dict = Body(default={})):
    """Voice mode: the browser relays GPT-Live's delegated function calls here."""
    _course(course)
    if name not in {t["name"] for t in tools.TOOLS}:
        raise HTTPException(404, f"unknown tool {name}")
    with db_lock:
        out, board = tools.run_tool(conn, course, name, args)
    return {"output": out, "board": board}


# ---------- text / economy voice / client-delegation brain turns ----------

class ChatReq(BaseModel):
    course: str
    mode: str = "guided"
    chat_id: str | None = None
    text: str = ""
    image: str | None = None   # data: URL
    screen: str | None = None  # description of the shared screen (from /api/vision/describe)


@app.post("/api/chat")
def chat(req: ChatReq):
    chat_obj = chats.get(req.chat_id or "")
    if chat_obj is None:
        course = _course(req.course)
        with db_lock:
            sid = spend.start_session(conn, req.course, req.mode, "text")
        chat_obj = brain.Chat(course=req.course, mode=req.mode, sid=sid,
                              instructions=prompts.brain_instructions(course, req.mode, _about_me()))
        chats[chat_obj.id] = chat_obj
    try:
        with chat_obj.turn_lock:
            res = brain.brain_turn(settings, conn, chat_obj, req.text, req.image, req.screen, db_lock=db_lock)
    except brain.OpenAIError as e:
        raise HTTPException(502, str(e))
    return {"chat_id": chat_obj.id, "sid": chat_obj.sid, **res}


# ---------- UI ----------

WEB = ROOT / "web"
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


def main() -> None:
    import uvicorn
    import webbrowser
    url = f"http://{settings.host}:{settings.port}"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
