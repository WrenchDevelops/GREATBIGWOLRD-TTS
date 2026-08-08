"""Kokoro TTS engine: one shared model, controlled concurrency, in-memory encoding."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np
import soundfile as sf
import torch

from app.config import Settings
from app.models import SUPPORTED_VOICES, VOICE_BY_ID

logger = logging.getLogger("kokoro_tts.engine")

CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
}


class TTSEngine:
    """Process-wide Kokoro engine with a single shared KModel."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sample_rate = settings.sample_rate
        self._model = None
        self._pipelines: dict[str, object] = {}
        self._ready = False
        self._default_voice = settings.default_voice
        self._init_seconds: Optional[float] = None
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_tts)
        # One worker thread per concurrent TTS slot keeps RAM predictable.
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_tts,
            thread_name_prefix="kokoro-tts",
        )

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def default_voice(self) -> str:
        return self._default_voice

    @property
    def init_seconds(self) -> Optional[float]:
        return self._init_seconds

    def initialize(self) -> None:
        """Load Kokoro once at startup. Safe to call only from lifespan startup."""
        if self._ready:
            return

        started = time.perf_counter()
        logger.info("Initializing Kokoro model repo=%s device=cpu", self.settings.model_repo)

        # Force CPU-only inference and avoid thread oversubscription.
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
        torch.set_num_threads(self.settings.torch_num_threads)
        torch.set_num_interop_threads(self.settings.torch_num_interop_threads)

        from kokoro import KModel, KPipeline

        model = KModel(repo_id=self.settings.model_repo).to("cpu").eval()
        self._model = model

        # Warm English pipelines (American + British) with the shared model.
        for lang_code in ("a", "b"):
            self._pipelines[lang_code] = KPipeline(
                lang_code=lang_code,
                repo_id=self.settings.model_repo,
                model=model,
                device="cpu",
            )

        voice = self.settings.default_voice
        if voice not in SUPPORTED_VOICES:
            logger.warning(
                "DEFAULT_VOICE=%s is not in the catalog; falling back to af_heart",
                voice,
            )
            voice = "af_heart"
            self._default_voice = voice

        # Verify default voice packs load and run a tiny warmup synthesis.
        pipeline = self._pipeline_for_voice(voice)
        pipeline.load_voice(voice)
        warmup_audio = self._synthesize_numpy("Kokoro ready.", voice=voice, speed=1.0)
        if warmup_audio.size == 0:
            raise RuntimeError("Warmup synthesis produced empty audio")

        self._ready = True
        self._init_seconds = time.perf_counter() - started
        logger.info(
            "Kokoro ready in %.2fs default_voice=%s concurrent=%s torch_threads=%s warmup_samples=%s",
            self._init_seconds,
            self._default_voice,
            self.settings.max_concurrent_tts,
            self.settings.torch_num_threads,
            int(warmup_audio.size),
        )

    def _pipeline_for_voice(self, voice: str):
        meta = VOICE_BY_ID.get(voice)
        if meta is None:
            raise ValueError(f"Unsupported voice: {voice}")

        lang_code = meta["lang_code"]
        pipeline = self._pipelines.get(lang_code)
        if pipeline is not None:
            return pipeline

        # Lazily create additional language pipelines, always reusing the shared model.
        from kokoro import KPipeline

        logger.info("Creating pipeline for lang_code=%s", lang_code)
        try:
            pipeline = KPipeline(
                lang_code=lang_code,
                repo_id=self.settings.model_repo,
                model=self._model,
                device="cpu",
            )
        except ImportError as exc:
            raise ValueError(
                f"Voice '{voice}' requires extra language dependencies that are not installed"
            ) from exc
        except Exception as exc:
            raise ValueError(f"Unable to initialize pipeline for voice '{voice}': {exc}") from exc

        self._pipelines[lang_code] = pipeline
        return pipeline

    def _synthesize_numpy(self, text: str, voice: str, speed: float) -> np.ndarray:
        pipeline = self._pipeline_for_voice(voice)
        chunks: list[np.ndarray] = []

        for result in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+"):
            audio = result.audio
            if audio is None:
                continue
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()
            arr = np.asarray(audio, dtype=np.float32).reshape(-1)
            if arr.size:
                chunks.append(arr)

        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def _encode_audio(self, audio: np.ndarray, fmt: str) -> bytes:
        fmt = fmt.lower()
        if fmt == "wav":
            buffer = io.BytesIO()
            sf.write(buffer, audio, self.sample_rate, format="WAV", subtype="PCM_16")
            return buffer.getvalue()

        if fmt == "mp3":
            return self._encode_mp3(audio)

        raise ValueError(f"Unsupported format: {fmt}")

    def _encode_mp3(self, audio: np.ndarray) -> bytes:
        """Encode float32 PCM to MP3 via ffmpeg pipes (no leftover temp files)."""
        wav_buffer = io.BytesIO()
        sf.write(wav_buffer, audio, self.sample_rate, format="WAV", subtype="PCM_16")
        wav_bytes = wav_buffer.getvalue()

        process = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "wav",
                "-i",
                "pipe:0",
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "2",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=wav_bytes,
            capture_output=True,
            check=False,
        )
        if process.returncode != 0:
            stderr = process.stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ffmpeg MP3 encoding failed: {stderr}")
        if not process.stdout:
            raise RuntimeError("ffmpeg returned empty MP3 output")
        return process.stdout

    def generate_sync(self, text: str, voice: str, speed: float, fmt: str) -> bytes:
        """Blocking synthesis + encode. Intended to run in the thread pool."""
        if not self._ready or self._model is None:
            raise RuntimeError("TTS engine is not initialized")
        if voice not in SUPPORTED_VOICES:
            raise ValueError(f"Unsupported voice: {voice}")

        audio = self._synthesize_numpy(text, voice=voice, speed=speed)
        if audio.size == 0:
            raise RuntimeError("Synthesis produced empty audio")
        return self._encode_audio(audio, fmt)

    async def generate(
        self,
        text: str,
        voice: str,
        speed: float,
        fmt: str,
        timeout_seconds: float,
    ) -> bytes:
        """Generate audio with concurrency limiting and timeout protection."""
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise TimeoutError("Timed out waiting for a free TTS worker") from exc

        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        remaining = max(0.1, timeout_seconds - (time.perf_counter() - started))
        future = loop.run_in_executor(
            self._executor,
            self.generate_sync,
            text,
            voice,
            speed,
            fmt,
        )

        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=remaining)
        except asyncio.TimeoutError as exc:
            # Keep the slot occupied until the worker finishes so RAM stays bounded.
            future.add_done_callback(lambda _f: self._semaphore.release())
            raise TimeoutError("TTS generation timed out") from exc
        except Exception:
            self._semaphore.release()
            raise
        else:
            self._semaphore.release()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._ready = False
