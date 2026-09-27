"""Function tools the brain (GPT-6 Luna) can call. Same tools serve voice and text mode."""
from __future__ import annotations

import json
from typing import Any

from . import page, progress, retrieval
from .db import Conn


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required,
                           "additionalProperties": False}}


TOOLS: list[dict] = [
    _fn("search_material",
        "Search this course's own material (slides, readings, labs, notes). Returns passages with "
        "sources. Use before teaching or grading anything course-specific.",
        {"query": {"type": "string", "description": "Keywords, e.g. 'NAT gateway private subnet'"},
         "k": {"type": "integer", "description": "How many passages (1-8)", "default": 5}},
        ["query"]),
    _fn("get_study_focus",
        "What Marc should work on: concepts due for review, weak ones, not started yet, recent "
        "misconceptions, and analogies that clicked before. Call at session start.",
        {}, []),
    _fn("record_attempt",
        "Record how Marc did on a concept after you check his understanding.",
        {"concept": {"type": "string", "description": "Concept name (reuse names from get_study_focus)"},
         "outcome": {"type": "string", "enum": list(progress.OUTCOMES)},
         "hint_level": {"type": "integer", "description": "Highest hint-ladder rung used, 0-5"},
         "misconception": {"type": "string", "description": "Specific wrong idea, if any"},
         "analogy": {"type": "string", "description": "Analogy used, if any"},
         "analogy_helped": {"type": "boolean"}},
        ["concept", "outcome", "hint_level"]),
    _fn("show_on_board",
        "Display code, math (LaTeX in $...$ / $$...$$), a diagram description, or steps on Marc's "
        "screen. Use instead of reading these aloud.",
        {"title": {"type": "string"},
         "markdown": {"type": "string", "description": "Markdown; fenced code blocks and LaTeX allowed"}},
        ["title", "markdown"]),
    _fn("read_page",
        "Read the EXACT text of the web page Marc is studying right now (e.g. a TestOut/Canvas lesson), "
        "synced live by his browser extension. Prefer this over look_at_screen for anything in his "
        "browser. Call it whenever he mentions the lesson, 'this section', a numbered topic like 1.1.1, "
        "or asks about what he's reading. The result includes `outline` (every section heading on the page); "
        "on long pages pass `focus` (a heading or keywords) to read that part. Cover all sections he asks about.",
        {"focus": {"type": "string", "description": "Optional: topic/keywords to jump to on a long page"}},
        []),
    _fn("look_at_screen",
        "See what's on Marc's screen right now (only works while he's sharing it). Returns a text "
        "description with any code, errors, or question text transcribed. Call it whenever he says "
        "'this', 'here', 'look', 'on my screen', mentions an error or lab step you can't see, or you're "
        "unsure what he's working on. Cheap when the screen hasn't changed.",
        {"question": {"type": "string", "description": "What you need to know from the screen"}},
        ["question"]),
]

# Server-side loops (text / economy / client delegation) get the screen as context with each turn instead.
SERVER_TOOLS = [t for t in TOOLS if t["name"] != "look_at_screen"]


def run_tool(conn: Conn, course: str, name: str, args: dict[str, Any]) -> tuple[str, dict | None]:
    """Execute a tool. Returns (output_for_model, board_update_or_None)."""
    try:
        if name == "search_material":
            k = max(1, min(8, int(args.get("k") or 5)))
            hits = retrieval.search(conn, course, args.get("query", ""), k)
            if not hits:
                return json.dumps({"results": [], "note": "Nothing in the course material matched."}), None
            return json.dumps({"results": hits}), None
        if name == "get_study_focus":
            return json.dumps(progress.study_focus(conn, course)), None
        if name == "record_attempt":
            res = progress.record_attempt(
                conn, course, args["concept"], args["outcome"], args.get("hint_level", 0),
                args.get("misconception", ""), args.get("analogy", ""), args.get("analogy_helped"))
            return json.dumps({"ok": True, **res}), None
        if name == "show_on_board":
            board = {"title": args.get("title", ""), "markdown": args.get("markdown", "")}
            return json.dumps({"ok": True, "shown": True}), board
        if name == "read_page":
            return json.dumps(page.read(args.get("focus", ""))), None
        if name == "look_at_screen":
            return json.dumps({"error": "Screen isn't shared right now. Ask Marc to click 'Share screen'."}), None
        return json.dumps({"error": f"unknown tool {name}"}), None
    except Exception as e:  # never crash the conversation over a tool
        return json.dumps({"error": str(e)}), None
