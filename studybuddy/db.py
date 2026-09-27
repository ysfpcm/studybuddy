"""SQLite storage: course material index (FTS5) + learner model."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    course TEXT NOT NULL,
    path TEXT NOT NULL,
    sha TEXT NOT NULL,
    kind TEXT,
    indexed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (course, path)
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    course TEXT NOT NULL,
    path TEXT NOT NULL,
    locator TEXT,          -- "p.4", "slide 12", "lines 10-40"
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_course ON chunks(course, path);

CREATE TABLE IF NOT EXISTS concepts (
    course TEXT NOT NULL,
    key TEXT NOT NULL,          -- normalized name
    name TEXT NOT NULL,
    unit TEXT,
    objective TEXT,
    mastery REAL DEFAULT 0.0,   -- 0..1
    attempts INTEGER DEFAULT 0,
    interval_days REAL DEFAULT 0,
    last_seen TEXT,
    next_review TEXT,
    PRIMARY KEY (course, key)
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    course TEXT NOT NULL,
    concept_key TEXT NOT NULL,
    outcome TEXT NOT NULL,      -- got_it | partial | missed
    hint_level INTEGER DEFAULT 0,
    misconception TEXT,
    analogy TEXT,
    analogy_helped INTEGER,
    at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    course TEXT NOT NULL,
    mode TEXT,
    channel TEXT,               -- live | economy | text
    started_at TEXT NOT NULL,
    ended_at TEXT,
    voice_seconds REAL DEFAULT 0,
    in_tokens INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    out_tokens INTEGER DEFAULT 0,
    vision_calls INTEGER DEFAULT 0,
    vision_cost REAL DEFAULT 0,
    cost_voice REAL DEFAULT 0,
    tts_seconds REAL DEFAULT 0,
    tts_cost REAL DEFAULT 0,
    cost_brain REAL DEFAULT 0,
    cost_total REAL DEFAULT 0,
    brain_reported INTEGER DEFAULT 1,   -- 0 if the API didn't report Luna usage (estimate only)
    transcript_file TEXT,
    raw_usage TEXT
);
"""

NOTES_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    course TEXT NOT NULL,
    id TEXT NOT NULL,           -- file path relative to the course folder
    summary TEXT,               -- AI breakdown (markdown)
    summary_hash TEXT,          -- hash of the text it summarized (re-summarize when the page changes)
    summary_at TEXT,
    full_summary TEXT,          -- optional detailed "full notes" breakdown (markdown)
    full_summary_hash TEXT,
    my_notes TEXT,             -- Marc's own notes for this section
    notes_at TEXT,
    PRIMARY KEY (course, id)
);
CREATE TABLE IF NOT EXISTS guides (
    course TEXT PRIMARY KEY,
    markdown TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS practice_sets (
    id INTEGER PRIMARY KEY,
    course TEXT NOT NULL,
    note_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    content TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'mini',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS practice_sets_note ON practice_sets(course, note_id, id);
CREATE TABLE IF NOT EXISTS practice_runs (
    id TEXT PRIMARY KEY,
    set_id INTEGER NOT NULL,
    course TEXT NOT NULL,
    note_id TEXT NOT NULL,
    content TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS practice_answers (
    run_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    choice INTEGER,
    mastery REAL NOT NULL,
    answered_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (run_id, item_id)
);
"""

FTS = "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content='chunks', content_rowid='id', tokenize='porter unicode61')"


class Conn(sqlite3.Connection):
    fts: bool = False  # True when FTS5 is available; otherwise LIKE search


def connect(path: Path | str) -> Conn:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, factory=Conn)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executescript(NOTES_SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    if "recap" not in cols:  # migrate older databases
        conn.execute("ALTER TABLE sessions ADD COLUMN recap TEXT")
    if "tts_seconds" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN tts_seconds REAL DEFAULT 0")
    if "tts_cost" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN tts_cost REAL DEFAULT 0")
    if "kind" not in {r[1] for r in conn.execute("PRAGMA table_info(practice_sets)")}:
        conn.execute("ALTER TABLE practice_sets ADD COLUMN kind TEXT NOT NULL DEFAULT 'mini'")
    if "content" not in {r[1] for r in conn.execute("PRAGMA table_info(practice_runs)")}:
        conn.execute("ALTER TABLE practice_runs ADD COLUMN content TEXT")
    if "full_summary" not in {r[1] for r in conn.execute("PRAGMA table_info(notes)")}:
        # Breakdowns written before the short format are the detailed version: keep them as full notes.
        conn.execute("ALTER TABLE notes ADD COLUMN full_summary TEXT")
        conn.execute("ALTER TABLE notes ADD COLUMN full_summary_hash TEXT")
        conn.execute("UPDATE notes SET full_summary=summary, full_summary_hash=summary_hash, summary=NULL, "
                     "summary_hash=NULL WHERE summary IS NOT NULL")
    try:
        conn.execute(FTS)
        conn.fts = True
    except sqlite3.OperationalError:
        conn.fts = False
    conn.commit()
    return conn
