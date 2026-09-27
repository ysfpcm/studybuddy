"""Spend tracking: every session gets a receipt (voice minutes + Luna tokens + screen looks)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .db import Conn


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def token_cost(s: Settings, in_tokens: int, cached: int, out_tokens: int) -> float:
    fresh = max(0, in_tokens - cached)
    return (fresh * s.price_brain_in + cached * s.price_brain_cached + out_tokens * s.price_brain_out) / 1_000_000


def usage_tokens(usage: dict | None) -> tuple[int, int, int]:
    """(input, cached_input, output) from a Responses-API style usage object."""
    if not usage:
        return 0, 0, 0
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
    return int(usage.get("input_tokens", 0) or 0), int(cached), int(usage.get("output_tokens", 0) or 0)


def merge_usage(total: dict, usage: dict | None) -> None:
    """Add a Responses API usage record to a mutable running total."""
    i, c, o = usage_tokens(usage)
    total["input_tokens"] = total.get("input_tokens", 0) + i
    total["output_tokens"] = total.get("output_tokens", 0) + o
    details = total.setdefault("input_tokens_details", {})
    details["cached_tokens"] = details.get("cached_tokens", 0) + c


def start_session(conn: Conn, course: str, mode: str, channel: str) -> str:
    sid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    conn.execute("INSERT INTO sessions(id, course, mode, channel, started_at) VALUES (?,?,?,?,?)",
                 (sid, course, mode, channel, _now()))
    conn.commit()
    return sid


def add_brain_usage(conn: Conn, sid: str | None, usage: dict | None) -> None:
    if not sid or not usage:
        return
    i, c, o = usage_tokens(usage)
    conn.execute("UPDATE sessions SET in_tokens=in_tokens+?, cached_tokens=cached_tokens+?, out_tokens=out_tokens+? "
                 "WHERE id=?", (i, c, o, sid))
    conn.commit()


def add_vision(conn: Conn, sid: str | None, cost: float) -> None:
    if not sid:
        return
    conn.execute("UPDATE sessions SET vision_calls=vision_calls+1, vision_cost=vision_cost+? WHERE id=?", (cost, sid))
    conn.commit()


def add_tts(conn: Conn, s: Settings, sid: str, seconds: float) -> None:
    """Estimate TTS spend from generated audio length; the speech API has no usage body."""
    cost = seconds / 60 * s.price_tts_est_per_min
    conn.execute("UPDATE sessions SET tts_seconds=tts_seconds+?, tts_cost=tts_cost+?, "
                 "cost_total=cost_total+CASE WHEN ended_at IS NOT NULL THEN ? ELSE 0 END WHERE id=?",
                 (seconds, cost, cost, sid))
    conn.commit()


def _find_number(obj: Any, want) -> float | None:
    """Depth-first search for the first numeric value whose key satisfies `want`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and want(k.lower()):
                return float(v) / (1000 if k.lower().endswith("_ms") else 1)
        for v in obj.values():
            r = _find_number(v, want)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_number(v, want)
            if r is not None:
                return r
    return None


def voice_seconds_from_usage(raw: dict | None) -> float | None:
    if not raw:
        return None
    return _find_number(raw, lambda k: ("duration" in k or "seconds" in k) and "token" not in k)


def close_session(conn: Conn, s: Settings, sid: str, measured_seconds: float = 0,
                  client_usage: dict | None = None, raw_usage: dict | None = None,
                  transcript_file: str | None = None) -> dict:
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if row is None:
        raise KeyError(sid)
    if row["ended_at"]:
        return receipt(conn, s, sid)  # idempotent
    # Luna usage reported by the browser (forwarded response.completed events in delegation mode)
    ci, cc, co = usage_tokens(client_usage)
    if not (ci or co) and raw_usage:  # otherwise try the session.closed usage payload
        ci = int(_find_number(raw_usage, lambda k: k == "input_tokens") or 0)
        co = int(_find_number(raw_usage, lambda k: k == "output_tokens") or 0)
        cc = int(_find_number(raw_usage, lambda k: k == "cached_tokens") or 0)
    in_t, cached_t, out_t = row["in_tokens"] + ci, row["cached_tokens"] + cc, row["out_tokens"] + co
    secs = 0.0
    if row["channel"] == "live":
        reported = voice_seconds_from_usage(raw_usage)
        secs = reported if reported else measured_seconds
    cost_voice = secs / 60 * s.price_live_per_min
    cost_brain = token_cost(s, in_t, cached_t, out_t)
    brain_reported = 0 if (row["channel"] == "live" and s.delegation_mode == "responses"
                           and in_t == 0 and out_t == 0) else 1
    total = cost_voice + cost_brain + row["vision_cost"] + row["tts_cost"]
    conn.execute(
        "UPDATE sessions SET ended_at=?, voice_seconds=?, in_tokens=?, cached_tokens=?, out_tokens=?, "
        "cost_voice=?, cost_brain=?, cost_total=?, brain_reported=?, transcript_file=?, raw_usage=? WHERE id=?",
        (_now(), round(secs, 1), in_t, cached_t, out_t, round(cost_voice, 5), round(cost_brain, 5),
         round(total, 5), brain_reported, transcript_file, json.dumps(raw_usage) if raw_usage else None, sid))
    conn.commit()
    return receipt(conn, s, sid)


def receipt(conn: Conn, s: Settings, sid: str) -> dict:
    r = dict(conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
    r.pop("raw_usage", None)
    r["month"] = month_summary(conn, s)
    return r


def month_summary(conn: Conn, s: Settings) -> dict:
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month = conn.execute("SELECT COALESCE(SUM(cost_total),0), COALESCE(SUM(voice_seconds),0), "
                         "COALESCE(SUM(channel != 'background'),0) "
                         "FROM sessions WHERE started_at >= ?", (month_start,)).fetchone()
    today = conn.execute("SELECT COALESCE(SUM(cost_total),0) FROM sessions WHERE started_at >= ?",
                         (day_start,)).fetchone()[0]
    by_channel = conn.execute("SELECT channel, ROUND(SUM(cost_total),4) AS cost, COUNT(*) AS n FROM sessions "
                              "WHERE started_at >= ? GROUP BY channel", (month_start,)).fetchall()
    spent = round(month[0], 4)
    return {"spent": spent, "today": round(today, 4), "budget": s.monthly_budget,
            "remaining": round(max(0.0, s.monthly_budget - spent), 4),
            "pct": round(100 * spent / s.monthly_budget, 1) if s.monthly_budget else 0,
            "voice_minutes": round(month[1] / 60, 1), "sessions": month[2],
            "by_channel": [dict(r) for r in by_channel]}


def recent(conn: Conn, limit: int = 8) -> list[dict]:
    rows = conn.execute("SELECT id, course, mode, channel, started_at, voice_seconds, cost_total, brain_reported "
                        "FROM sessions WHERE ended_at IS NOT NULL ORDER BY started_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def over_budget(conn: Conn, s: Settings) -> bool:
    return s.monthly_budget > 0 and month_summary(conn, s)["spent"] >= s.monthly_budget


def charge_background(conn: Conn, s: Settings, course: str, label: str, usage: dict | None) -> float:
    """Record AI work that isn't part of a chat (summaries, recaps, study guide) so monthly spend stays honest."""
    sid = start_session(conn, course, label, "background")
    add_brain_usage(conn, sid, usage)
    return close_session(conn, s, sid)["cost_total"]
