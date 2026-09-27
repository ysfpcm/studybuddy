"""Settings loaded from .env (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# One set of effort choices for all Luna work. The interactive choice is user-configurable.
TASK_EFFORT = {"concept_map": "medium", "breakdown": "medium", "breakdown_repair": "medium",
               "breakdown_trim": "low",
               "recap": "low", "study_guide": "medium", "practice": "medium", "vision": "none"}


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default)).expanduser()
    return p if p.is_absolute() else (ROOT / p)


@dataclass
class Settings:
    api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    api_base: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    # Voice layer (full-duplex speech)
    live_model: str = field(default_factory=lambda: os.getenv("LIVE_MODEL", "gpt-live-1"))
    voice: str = field(default_factory=lambda: os.getenv("LIVE_VOICE", "marin"))
    tts_voice: str = field(default_factory=lambda: os.getenv("TTS_VOICE", "marin"))
    # Brain (reasoning backend GPT-Live delegates to; also used for text mode)
    brain_model: str = field(default_factory=lambda: os.getenv("BRAIN_MODEL", "gpt-6-luna"))
    brain_effort: str = field(default_factory=lambda: os.getenv("BRAIN_REASONING_EFFORT", "low"))
    # "responses" = GPT-Live calls the brain directly (managed).
    # "client"    = fallback: our server calls the brain and injects results.
    delegation_mode: str = field(default_factory=lambda: os.getenv("DELEGATION_MODE", "responses"))
    max_session_minutes: int = field(default_factory=lambda: int(os.getenv("MAX_SESSION_MINUTES", "45")))
    # End a premium voice session after this much silence (billing is per second of session time)
    idle_end_seconds: int = field(default_factory=lambda: int(os.getenv("IDLE_END_SECONDS", "180")))
    # Spend control (USD). Premium voice is blocked once the month's spend reaches the budget.
    monthly_budget: float = field(default_factory=lambda: float(os.getenv("MONTHLY_BUDGET", "25")))
    # Prices (USD). Update if OpenAI changes pricing.
    price_live_per_min: float = field(default_factory=lambda: float(os.getenv("PRICE_LIVE_PER_MIN", "0.05")))
    price_tts_est_per_min: float = field(default_factory=lambda: float(os.getenv("PRICE_TTS_EST_PER_MIN", "0.015")))
    price_brain_in: float = field(default_factory=lambda: float(os.getenv("PRICE_BRAIN_IN_PER_M", "0.20")))
    price_brain_cached: float = field(default_factory=lambda: float(os.getenv("PRICE_BRAIN_CACHED_PER_M", "0.02")))
    price_brain_out: float = field(default_factory=lambda: float(os.getenv("PRICE_BRAIN_OUT_PER_M", "1.00")))
    # Screen "eyes": openai (uses BRAIN_MODEL) or ollama (free, local vision model)
    vision_provider: str = field(default_factory=lambda: os.getenv("VISION_PROVIDER", "openai"))
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    ollama_vision_model: str = field(default_factory=lambda: os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:7b"))
    courses_dir: Path = field(default_factory=lambda: _path("COURSES_DIR", "courses"))
    data_dir: Path = field(default_factory=lambda: _path("DATA_DIR", "data"))
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8765")))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studybuddy.db"

    @property
    def profile_path(self) -> Path:
        return self.data_dir / "about_me.md"

    def effort(self, task: str) -> str:
        return self.brain_effort if task == "chat" else TASK_EFFORT[task]


settings = Settings()
