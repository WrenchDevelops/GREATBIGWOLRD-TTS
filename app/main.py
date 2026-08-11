"""FastAPI entrypoint for the Kokoro TTS service."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import __version__
from app.cache import AudioCache
from app.config import Settings, get_settings
from app.models import (
    SUPPORTED_VOICES,
    VOICE_CATALOG,
    HealthResponse,
    TTSRequest,
    VoiceInfo,
    VoicesResponse,
)
from app.tts import CONTENT_TYPES, TTSEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("kokoro_tts.api")

bearer_scheme = HTTPBearer(auto_error=False)

engine: Optional[TTSEngine] = None
audio_cache: Optional[AudioCache] = None


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.getLogger().setLevel(level)
    logging.getLogger("kokoro_tts").setLevel(level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, audio_cache

    settings = get_settings()
    configure_logging(settings)

    logger.info(
        "Starting Kokoro TTS API v%s max_concurrent=%s cache_dir=%s",
        __version__,
        settings.max_concurrent_tts,
        settings.cache_dir,
    )

    audio_cache = AudioCache(
        cache_dir=settings.cache_dir,
        max_bytes=settings.cache_max_bytes,
        enabled=settings.cache_enabled,
    )

    engine = TTSEngine(settings)
    try:
        engine.initialize()
    except Exception:
        logger.exception("Failed to initialize Kokoro")
        raise

    app.state.settings = settings
    app.state.engine = engine
    app.state.cache = audio_cache

    yield

    if engine is not None:
        engine.shutdown()
    logger.info("Kokoro TTS API shutdown complete")


app = FastAPI(
    title="Kokoro TTS API",
    description="Self-hosted Kokoro text-to-speech API optimized for CPU Railway deployments.",
    version=__version__,
    lifespan=lifespan,
)

_settings_for_cors = get_settings()
if _settings_for_cors.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings_for_cors.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        expose_headers=[
            "X-TTS-Cache",
            "X-TTS-Generation-Time",
            "X-TTS-Voice",
            "X-TTS-Format",
        ],
    )
else:
    logger.info("CORS disabled (set ALLOWED_ORIGINS to enable)")


def get_engine() -> TTSEngine:
    if engine is None or not engine.ready:
        raise HTTPException(status_code=503, detail="TTS engine is not ready")
    return engine


def get_cache() -> AudioCache:
    if audio_cache is None:
        raise HTTPException(status_code=503, detail="Cache is not ready")
    return audio_cache


async def require_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.api_key_required:
        return
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    ready = engine is not None and engine.ready
    if not ready:
        # Lifespan normally blocks until ready; this covers edge restart windows.
        raise HTTPException(status_code=503, detail="TTS engine is starting")
    return HealthResponse(
        status="ok",
        model_loaded=True,
        default_voice=settings.default_voice,
        ready=True,
    )


@app.get("/warmup", response_model=HealthResponse, include_in_schema=False)
async def warmup(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Alias of /health for clients that keep the Railway service warm."""
    return await health(settings)


@app.get("/voices", response_model=VoicesResponse, dependencies=[Depends(require_api_key)])
async def list_voices(settings: Settings = Depends(get_settings)) -> VoicesResponse:
    voices = [
        VoiceInfo(
            id=item["id"],
            name=item["name"],
            language=item["language"],
            lang_code=item["lang_code"],
            gender=item["gender"],
            grade=item.get("grade"),
            traits=item.get("traits"),
            default=item["id"] == settings.default_voice,
        )
        for item in VOICE_CATALOG
    ]
    return VoicesResponse(
        default_voice=settings.default_voice,
        count=len(voices),
        voices=voices,
    )


@app.post("/tts", dependencies=[Depends(require_api_key)])
async def synthesize(
    body: TTSRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    tts: TTSEngine = Depends(get_engine),
    cache: AudioCache = Depends(get_cache),
) -> Response:
    started = time.perf_counter()
    text = body.text
    voice = body.voice or settings.default_voice
    speed = body.speed
    fmt = (body.format or settings.default_format).lower()

    if len(text) > settings.max_text_length:
        raise HTTPException(
            status_code=400,
            detail=f"text exceeds maximum length of {settings.max_text_length} characters",
        )
    if voice not in SUPPORTED_VOICES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported voice '{voice}'. Use GET /voices for available options.",
        )
    if speed < settings.min_speed or speed > settings.max_speed:
        raise HTTPException(
            status_code=400,
            detail=f"speed must be between {settings.min_speed} and {settings.max_speed}",
        )
    if fmt not in CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="format must be 'mp3' or 'wav'")

    logger.info(
        "request received path=/tts chars=%s voice=%s speed=%.2f format=%s client=%s",
        len(text),
        voice,
        speed,
        fmt,
        request.client.host if request.client else "unknown",
    )

    cache_key = AudioCache.make_key(text, voice, speed, fmt)
    cached = cache.get(cache_key, fmt)
    if cached is not None:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "cache hit chars=%s voice=%s format=%s generation_ms=%s",
            len(text),
            voice,
            fmt,
            elapsed_ms,
        )
        return Response(
            content=cached,
            media_type=CONTENT_TYPES[fmt],
            headers={
                "X-TTS-Cache": "HIT",
                "X-TTS-Generation-Time": str(elapsed_ms),
                "X-TTS-Voice": voice,
                "X-TTS-Format": fmt,
                "Content-Disposition": f'inline; filename="speech.{fmt}"',
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    logger.info("cache miss chars=%s voice=%s format=%s", len(text), voice, fmt)

    try:
        audio_bytes = await tts.generate(
            text=text,
            voice=voice,
            speed=speed,
            fmt=fmt,
            timeout_seconds=settings.request_timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        logger.error("generation timeout chars=%s voice=%s detail=%s", len(text), voice, exc)
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("generation failed chars=%s voice=%s", len(text), voice)
        raise HTTPException(status_code=500, detail="Speech generation failed") from exc

    cache.put(cache_key, fmt, audio_bytes)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "generation complete chars=%s voice=%s format=%s bytes=%s generation_ms=%s",
        len(text),
        voice,
        fmt,
        len(audio_bytes),
        elapsed_ms,
    )

    return Response(
        content=audio_bytes,
        media_type=CONTENT_TYPES[fmt],
        headers={
            "X-TTS-Cache": "MISS",
            "X-TTS-Generation-Time": str(elapsed_ms),
            "X-TTS-Voice": voice,
            "X-TTS-Format": fmt,
            "Content-Disposition": f'inline; filename="speech.{fmt}"',
            "Cache-Control": "no-store",
        },
    )

