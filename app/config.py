"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _parse_origins(raw: Optional[str]) -> list[str]:
    if raw is None:
        return []
    value = raw.strip()
    if not value:
        return []
    if value == "*":
        return ["*"]
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the Kokoro TTS service."""

    host: str = "0.0.0.0"
    port: int = 8000
    api_key: Optional[str] = None
    allowed_origins: list[str] = field(default_factory=list)

    default_voice: str = "af_heart"
    default_format: str = "mp3"
    max_text_length: int = 2000
    min_speed: float = 0.5
    max_speed: float = 2.0

    # Concurrency: keep at 1 — one ONNX session is not safe for overlapping Run().
    max_concurrent_tts: int = 1
    request_timeout_seconds: float = 120.0
    onnx_num_threads: int = 4

    cache_dir: str = "/app/cache"
    cache_max_bytes: int = 512 * 1024 * 1024  # 512 MB
    cache_enabled: bool = True

    model_path: str = "/models/kokoro-v1.0.onnx"
    voices_path: str = "/models/voices-v1.0.bin"
    sample_rate: int = 24000
    log_level: str = "INFO"

    @property
    def api_key_required(self) -> bool:
        return bool(self.api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache settings from the environment."""
    # ONNX_NUM_THREADS is preferred; TORCH_NUM_THREADS is accepted for old Railway env.
    onnx_threads = _env_int("ONNX_NUM_THREADS", _env_int("TORCH_NUM_THREADS", 4))
    return Settings(
        host=os.getenv("HOST", "0.0.0.0"),
        port=_env_int("PORT", 8000),
        api_key=os.getenv("API_KEY") or None,
        allowed_origins=_parse_origins(os.getenv("ALLOWED_ORIGINS")),
        default_voice=os.getenv("DEFAULT_VOICE", "af_heart"),
        default_format=os.getenv("DEFAULT_FORMAT", "mp3").lower(),
        max_text_length=_env_int("MAX_TEXT_LENGTH", 2000),
        min_speed=_env_float("MIN_SPEED", 0.5),
        max_speed=_env_float("MAX_SPEED", 2.0),
        max_concurrent_tts=max(1, _env_int("MAX_CONCURRENT_TTS", 1)),
        request_timeout_seconds=_env_float("REQUEST_TIMEOUT_SECONDS", 120.0),
        onnx_num_threads=max(1, onnx_threads),
        cache_dir=os.getenv("CACHE_DIR", "/app/cache"),
        cache_max_bytes=_env_int("CACHE_MAX_BYTES", 512 * 1024 * 1024),
        cache_enabled=_env_bool("CACHE_ENABLED", True),
        model_path=os.getenv("MODEL_PATH", "/models/kokoro-v1.0.onnx"),
        voices_path=os.getenv("VOICES_PATH", "/models/voices-v1.0.bin"),
        sample_rate=_env_int("SAMPLE_RATE", 24000),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
