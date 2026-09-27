"""Learner model: per-concept mastery + spaced review scheduling.

Mastery (0..1) moves toward 1 when you get something right without much help,
and drops when you miss. Needing heavy hints counts as a partial.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .db import Conn

OUTCOMES = ("got_it", "partial", "missed")


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def key_of(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def upsert_concept(conn: Conn, course: str, name: str, unit: str = "", objective: str = "") -> str:
    key = key_of(name)
    conn.execute(
        "INSERT INTO concepts(course, key, name, unit, objective) VALUES (?,?,?,?,?) "
        "ON CONFLICT(course, key) DO UPDATE SET "
        "unit = COALESCE(NULLIF(excluded.unit, ''), concepts.unit), "
        "objective = COALESCE(NULLIF(excluded.objective, ''), concepts.objective)",
        (course, key, name.strip(), unit, objective))
    return key


def update_mastery(mastery: float, interval: float, outcome: str, hint_level: int) -> tuple[float, float]:
    """Return (new_mastery, new_interval_days)."""
    if outcome == "got_it" and hint_level >= 3:  # needed a partial step or worked example
        outcome = "partial"
    if outcome == "got_it":
        gain = 0.35 if hint_level == 0 else 0.25
        mastery += (1 - mastery) * gain
        interval = 1.0 if interval < 1 else interval * 2.2
    elif outcome == "partial":
        mastery += (0.55 - mastery) * 0.3
        interval = 1.0
    else:
        mastery *= 0.6
        interval = 0.0  # revisit this session / today
    return round(max(0.0, min(1.0, mastery)), 3), round(min(interval, 60.0), 2)


def record_attempt(conn: Conn, course: str, concept: str, outcome: str, hint_level: int = 0,
                   misconception: str = "", analogy: str = "", analogy_helped: bool | None = None) -> dict:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    hint_level = max(0, min(5, int(hint_level)))
    key = upsert_concept(conn, course, concept)
    row = conn.execute("SELECT mastery, interval_days, attempts FROM concepts WHERE course=? AND key=?",
                       (course, key)).fetchone()
    mastery, interval = update_mastery(row["mastery"], row["interval_days"], outcome, hint_level)
    t = now()
    nxt = t + (timedelta(days=interval) if interval else timedelta(minutes=10))
    conn.execute(
        "UPDATE concepts SET mastery=?, interval_days=?, attempts=attempts+1, last_seen=?, next_review=? "
        "WHERE course=? AND key=?", (mastery, interval, t.isoformat(), nxt.isoformat(), course, key))
    conn.execute(
        "INSERT INTO attempts(course, concept_key, outcome, hint_level, misconception, analogy, analogy_helped) "
        "VALUES (?,?,?,?,?,?,?)",
        (course, key, outcome, hint_level, misconception or None, analogy or None,
         None if analogy_helped is None else int(bool(analogy_helped))))
    conn.commit()
    return {"concept": concept, "mastery": mastery, "next_review": nxt.isoformat()}


def study_focus(conn: Conn, course: str, limit: int = 6) -> dict:
    t = now().isoformat()
    due = conn.execute(
        "SELECT name, mastery, next_review FROM concepts WHERE course=? AND next_review IS NOT NULL "
        "AND next_review <= ? ORDER BY mastery ASC LIMIT ?", (course, t, limit)).fetchall()
    unseen = conn.execute(
        "SELECT name, unit FROM concepts WHERE course=? AND attempts=0 ORDER BY unit, rowid LIMIT ?",
        (course, limit)).fetchall()
    weak = conn.execute(
        "SELECT name, mastery FROM concepts WHERE course=? AND attempts>0 AND mastery < 0.6 "
        "ORDER BY mastery ASC LIMIT ?", (course, limit)).fetchall()
    mistakes = conn.execute(
        "SELECT c.name, a.misconception FROM attempts a JOIN concepts c "
        "ON c.course=a.course AND c.key=a.concept_key WHERE a.course=? AND a.misconception IS NOT NULL "
        "ORDER BY a.id DESC LIMIT ?", (course, limit)).fetchall()
    analogies = conn.execute(
        "SELECT c.name, a.analogy FROM attempts a JOIN concepts c "
        "ON c.course=a.course AND c.key=a.concept_key WHERE a.course=? AND a.analogy_helped=1 "
        "ORDER BY a.id DESC LIMIT ?", (course, limit)).fetchall()
    return {
        "due_for_review": [dict(r) for r in due],
        "weak": [dict(r) for r in weak],
        "not_started": [dict(r) for r in unseen],
        "recent_misconceptions": [dict(r) for r in mistakes],
        "analogies_that_clicked": [dict(r) for r in analogies],
    }


def overview(conn: Conn, course: str) -> list[dict]:
    rows = conn.execute(
        "SELECT name, unit, mastery, attempts, next_review FROM concepts WHERE course=? "
        "ORDER BY unit, rowid", (course,)).fetchall()
    return [dict(r) for r in rows]
