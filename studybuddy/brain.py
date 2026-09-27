"""OpenAI calls: GPT-Live-1 session creation and the GPT-6 Luna tool loop (text + client-delegation mode)."""
from __future__ import annotations

import json
import threading
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import prompts, spend, tools
from .config import Settings
from .db import Conn


class OpenAIError(RuntimeError):
    pass


def _headers(s: Settings) -> dict:
    if not s.api_key:
        raise OpenAIError("OPENAI_API_KEY is not set. Put it in the .env file.")
    return {"Authorization": f"Bearer {s.api_key}", "Content-Type": "application/json"}


def _post(s: Settings, path: str, body: dict, timeout: float = 120) -> dict:
    r = httpx.post(f"{s.api_base}{path}", headers=_headers(s), json=body, timeout=timeout)
    if r.status_code >= 400:
        raise OpenAIError(f"{path} -> {r.status_code}: {r.text[:800]}")
    return r.json()


def _post_flex(s: Settings, path: str, body: dict, timeout: float = 600) -> dict:
    """Background work at the Flex tier (about 50% cheaper, slower). Falls back to standard if Flex is busy."""
    try:
        return _post(s, path, {**body, "service_tier": "flex"}, timeout=timeout)
    except OpenAIError as e:
        if any(code in str(e) for code in ("429", "resource_unavailable", "service_tier")):
            return _post(s, path, body, timeout=timeout)
        raise


def synthesize_speech(s: Settings, text: str) -> bytes:
    """Generate one Economy voice reply; keep the API key on the server."""
    path = "/audio/speech"
    r = httpx.post(f"{s.api_base}{path}", headers=_headers(s), json={
        "model": "gpt-4o-mini-tts", "voice": s.tts_voice, "input": text,
        "instructions": "Speak naturally, warmly, and conversationally, like a patient tutor.",
        "response_format": "wav",
    }, timeout=120)
    if r.status_code >= 400:
        raise OpenAIError(f"{path} -> {r.status_code}: {r.text[:800]}")
    return r.content


# ---------------- GPT-Live-1 ----------------

def live_session_config(s: Settings, voice_instr: str, brain_instr: str) -> dict:
    cfg: dict[str, Any] = {
        "model": s.live_model,
        "instructions": voice_instr,
        "audio": {"output": {"voice": s.voice}},  # format is negotiated by SDP over WebRTC
    }
    if s.delegation_mode == "client":
        cfg["delegation"] = {"type": "client"}
    else:
        cfg["delegation"] = {
            "type": "responses",
            "responses": {
                "model": s.brain_model,
                "instructions": brain_instr,
                "tools": tools.TOOLS,
                "tool_choice": "auto",
                "parallel_tool_calls": True,
                "reasoning": {"effort": s.brain_effort},
            },
        }
    return cfg


def create_live_session(s: Settings, offer_sdp: str, session_cfg: dict) -> dict:
    """Server-side half of the WebRTC handshake. The API key never reaches the browser."""
    return _post(s, "/live/sessions", {"session": session_cfg, "transport": {"type": "webrtc", "sdp": offer_sdp}},
                 timeout=30)


# ---------------- GPT-6 Luna tool loop ----------------

@dataclass
class Chat:
    course: str
    mode: str
    instructions: str
    sid: str | None = None              # spend-tracking session id
    previous_response_id: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    turn_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def _output_text(resp: dict) -> str:
    parts = []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text"):
                    parts.append(c.get("text", ""))
    return "".join(parts).strip()


def response_text(s: Settings, prompt: str | list[dict], task: str, *, flex: bool = False,
                  timeout: float | None = None, **options) -> tuple[str, dict | None]:
    """Make one Luna text response and return its text with the usage receipt."""
    body = {"model": s.brain_model, "input": prompt,
            "reasoning": {"effort": s.effort(task)}, **options}
    post = _post_flex if flex else _post
    resp = post(s, "/responses", body, timeout=timeout or (600 if flex else 120))
    return _output_text(resp), resp.get("usage")


def brain_turn(s: Settings, conn: Conn, chat: Chat, text: str, image_data_url: str | None = None,
               screen: str | None = None, max_steps: int = 8, db_lock=None) -> dict:
    """One tutor turn: run Luna with tools until it produces a reply. Returns {text, boards}.
    `screen` is a text description of Marc's screen right now (from the eyes), if sharing."""
    text = text or "(Marc sent an image of his work.)"
    if screen:
        text = f"[What's on Marc's screen right now: {screen}]\n\n{text}"
    content: list[dict] = [{"type": "input_text", "text": text}]
    if image_data_url:
        content.append({"type": "input_image", "image_url": image_data_url})
    pending_input: list[dict] = [{"role": "user", "content": content}]
    boards: list[dict] = []
    for _ in range(max_steps):
        body = {
            "model": s.brain_model,
            "instructions": chat.instructions,
            "input": pending_input,
            "tools": tools.SERVER_TOOLS,
            "reasoning": {"effort": s.effort("chat")},
            # Same key every turn of a course+mode keeps the long instructions in OpenAI's prompt
            # cache: cached input costs 10x less than fresh input.
            "prompt_cache_key": f"studybuddy-{chat.course}-{chat.mode}",
        }
        if chat.previous_response_id:
            body["previous_response_id"] = chat.previous_response_id
        resp = _post(s, "/responses", body)
        chat.previous_response_id = resp.get("id")
        with db_lock or nullcontext():
            spend.add_brain_usage(conn, chat.sid, resp.get("usage"))
        calls = [i for i in resp.get("output", []) if i.get("type") == "function_call"]
        if not calls:
            return {"text": _output_text(resp), "boards": boards}
        pending_input = []
        for call in calls:
            try:
                args = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            with db_lock or nullcontext():
                out, board = tools.run_tool(conn, chat.course, call["name"], args)
            if board:
                boards.append(board)
            pending_input.append({"type": "function_call_output", "call_id": call["call_id"], "output": out})
    return {"text": "Sorry, I got tangled up there. Can you say that again?", "boards": boards}


def extract_concepts(s: Settings, material: str) -> tuple[list[dict], dict | None]:
    """Returns (concepts, usage). Runs at the Flex tier since nobody is waiting on a voice reply."""
    from .prompts import CONCEPT_MAP_PROMPT
    text, usage = response_text(s, CONCEPT_MAP_PROMPT + material, "concept_map", flex=True)
    return parse_concepts(text), usage


# ---------------- Eyes: describe a screenshot ----------------





def describe_screen(s: Settings, image_data_url: str, question: str = "", kind: str = "screen") -> tuple[str, float]:
    """Image -> compact text context. Returns (description, cost_usd).
    kind="screen": a live look at the shared screen. kind="paste": a screenshot/photo Marc pasted.
    The image is used once and discarded; only this text goes into the conversation."""
    if kind == "paste":
        prompt = prompts.PASTE_PROMPT.format(question=question or "(no message — figure out what he needs help with)")
    else:
        prompt = prompts.VISION_PROMPT.format(question=question or "what he is working on")
    if s.vision_provider == "ollama":
        b64 = image_data_url.split(",", 1)[-1]
        r = httpx.post(f"{s.ollama_url}/api/chat", timeout=120, json={
            "model": s.ollama_vision_model, "stream": False,
            "messages": [{"role": "user", "content": prompt, "images": [b64]}]})
        if r.status_code >= 400:
            raise OpenAIError(f"ollama -> {r.status_code}: {r.text[:300]}")
        return r.json().get("message", {}).get("content", "").strip(), 0.0
    text, usage = response_text(s, [{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": image_data_url, "detail": "high" if kind == "paste" else "auto"}]}],
        "vision", max_output_tokens=1200 if kind == "paste" else 600,
        store=False, timeout=60)  # don't keep the image on OpenAI's side either
    i, c, o = spend.usage_tokens(usage)
    return text, spend.token_cost(s, i, c, o)


def parse_concepts(raw: str) -> list[dict]:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise OpenAIError("Concept map response had no JSON")
    data = json.loads(raw[start:end + 1])
    return [c for c in data.get("concepts", []) if isinstance(c, dict) and c.get("name")]
