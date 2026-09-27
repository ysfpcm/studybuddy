"""Keyword (BM25) search over one course's material. Scoped per course so classes never mix."""
from __future__ import annotations

import re

from .db import Conn

_STOP = {"the", "a", "an", "of", "to", "in", "is", "and", "or", "for", "on", "what", "how", "why",
         "does", "do", "it", "this", "that", "with", "are", "be", "as", "by", "at", "from", "can"}


def _terms(query: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_]+", query.lower())
    return [w for w in words if w not in _STOP and len(w) > 1][:12]


def search(conn: Conn, course: str, query: str, k: int = 5) -> list[dict]:
    terms = _terms(query)
    if not terms:
        return []
    if conn.fts:
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = conn.execute(
            "SELECT c.path, c.locator, c.text, bm25(chunks_fts) AS score "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            "WHERE chunks_fts MATCH ? AND c.course = ? ORDER BY score LIMIT ?",
            (match, course, k)).fetchall()
    else:
        like = " + ".join("(instr(lower(text), ?) > 0)" for _ in terms)
        rows = conn.execute(
            f"SELECT path, locator, text, -({like}) AS score FROM chunks WHERE course = ? "
            f"ORDER BY score LIMIT ?", (*terms, course, k)).fetchall()
        rows = [r for r in rows if r["score"] < 0]
    return [{"source": f"{r['path']} {r['locator']}".strip(), "text": r["text"]} for r in rows]
