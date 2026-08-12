"""Kokoro TTS engine: one ONNX session, controlled concurrency, in-memory encoding."""

from __future__ import annotations

import asyncio
import gc
import io
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np
import onnxruntime as ort
import soundfile as sf
from kokoro_onnx import Kokoro

from app.config import Settings
from app.models import SUPPORTED_VOICES, espeak_lang_for_voice

logger = logging.getLogger("kokoro_tts.engine")

CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
}


def rss_mb() -> int:
    """Current process RSS in MiB, or 0 if unavailable."""
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


class TTSEngine:
    """Process-wide Kokoro ONNX engine. One session, one in-flight generation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sample_rate = settings.sample_rate
        self._kokoro: Optional[Kokoro] = None
        self._available_voices: set[str] = set()
        self._ready = False
        self._default_voice = settings.default_voice
        self._init_seconds: Optional[float] = None
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_tts)
        # ONNX session Run() is not safe to overlap on one session.
        self._infer_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_tts,
            thread_name_prefix="kokoro-tts",
        )
        self._consecutive_timeouts = 0
        self._active_generations = 0
        self._active_started_at: Optional[float] = None
        self._stats_lock = threading.Lock()
        self._exit_started = False

    @property
    def ready(self) -> bool:
        if not self._ready:
            return False
        if self._workers_appear_stuck():
            self._mark_unhealthy_and_exit("worker appears stuck")
            return False
        return True

    @property
    def default_voice(self) -> str:
        return self._default_voice

    @property
    def init_seconds(self) -> Optional[float]:
        return self._init_seconds

    @property
    def available_voices(self) -> set[str]:
        return set(self._available_voices)

    def _workers_appear_stuck(self) -> bool:
        with self._stats_lock:
            if self._active_generations <= 0 or self._active_started_at is None:
                return False
            stuck_after = max(180.0, self.settings.request_timeout_seconds * 2)
            return (time.perf_counter() - self._active_started_at) > stuck_after

    def _mark_unhealthy_and_exit(self, reason: str) -> None:
        """Fail health and exit so Railway/Docker replace the replica.

        Serving 503 forever after a wedged/OOM worker is how the app falls
        back to on-device TTS. A process exit is the recovery path.
        """
        self._ready = False
        if self._exit_started:
            return
        self._exit_started = True
        logger.error(
            "TTS engine unhealthy (%s) rss_mb=%s; exiting so the platform restarts",
            reason,
            rss_mb(),
        )
        threading.Thread(target=self._exit_soon, name="tts-exit", daemon=True).start()

    @staticmethod
    def _exit_soon() -> None:
        time.sleep(0.25)
        os._exit(1)

    def initialize(self) -> None:
        """Load Kokoro ONNX once at startup. Safe to call only from lifespan startup."""
        if self._ready:
            return

        started = time.perf_counter()
        logger.info(
            "Initializing Kokoro ONNX model=%s voices=%s threads=%s rss_mb=%s",
            self.settings.model_path,
            self.settings.voices_path,
            self.settings.onnx_num_threads,
            rss_mb(),
        )

        if not os.path.isfile(self.settings.model_path):
            raise FileNotFoundError(f"ONNX model not found: {self.settings.model_path}")
        if not os.path.isfile(self.settings.voices_path):
            raise FileNotFoundError(f"Voice pack not found: {self.settings.voices_path}")

        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = self.settings.onnx_num_threads
        sess_options.inter_op_num_threads = 1
        sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.enable_mem_pattern = True
        sess_options.enable_cpu_mem_arena = True

        if hasattr(Kokoro, "from_session"):
            session = ort.InferenceSession(
                self.settings.model_path,
                sess_options=sess_options,
                providers=["CPUExecutionProvider"],
            )
            kokoro = Kokoro.from_session(session, self.settings.voices_path)
        else:
            kokoro = Kokoro(self.settings.model_path, self.settings.voices_path)
        self._kokoro = kokoro
        self._available_voices = {name.lower() for name in kokoro.get_voices()}

        voice = self.settings.default_voice
        if voice not in self._available_voices:
            fallback = "af_heart" if "af_heart" in self._available_voices else next(
                iter(sorted(self._available_voices)),
                "",
            )
            logger.warning(
                "DEFAULT_VOICE=%s is not in the ONNX voice pack; falling back to %s",
                voice,
                fallback,
            )
            voice = fallback
            self._default_voice = voice
        if not voice:
            raise RuntimeError("ONNX voice pack contains no voices")

        warmup_audio = self._synthesize_numpy("Kokoro ready.", voice=voice, speed=1.0)
        if warmup_audio.size == 0:
            raise RuntimeError("Warmup synthesis produced empty audio")
        del warmup_audio
        gc.collect()

        self._ready = True
        self._consecutive_timeouts = 0
        self._init_seconds = time.perf_counter() - started
        logger.info(
            "Kokoro ready in %.2fs default_voice=%s concurrent=%s onnx_threads=%s voices=%s rss_mb=%s",
            self._init_seconds,
            self._default_voice,
            self.settings.max_concurrent_tts,
            self.settings.onnx_num_threads,
            len(self._available_voices),
            rss_mb(),
        )

    def _synthesize_numpy(self, text: str, voice: str, speed: float) -> np.ndarray:
        if self._kokoro is None:
            raise RuntimeError("TTS engine is not initialized")
        lang = espeak_lang_for_voice(voice)
        audio, sample_rate = self._kokoro.create(
            text,
            voice=voice,
            speed=speed,
            lang=lang,
        )
        if sample_rate:
            self.sample_rate = int(sample_rate)
        arr = np.asarray(audio, dtype=np.float32).reshape(-1)
        return arr

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
        wav_buffer.close()

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
        del wav_bytes
        if process.returncode != 0:
            stderr = process.stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ffmpeg MP3 encoding failed: {stderr}")
        if not process.stdout:
            raise RuntimeError("ffmpeg returned empty MP3 output")
        return process.stdout

    def generate_sync(self, text: str, voice: str, speed: float, fmt: str) -> bytes:
        """Blocking synthesis + encode. Intended to run in the thread pool."""
        if not self._ready or self._kokoro is None:
            raise RuntimeError("TTS engine is not initialized")
        if voice not in self._available_voices:
            if voice not in SUPPORTED_VOICES:
                raise ValueError(f"Unsupported voice: {voice}")
            raise ValueError(f"Voice '{voice}' is not in the loaded ONNX voice pack")

        with self._infer_lock:
            with self._stats_lock:
                self._active_generations += 1
                if self._active_started_at is None:
                    self._active_started_at = time.perf_counter()
            try:
                audio = self._synthesize_numpy(text, voice=voice, speed=speed)
            finally:
                with self._stats_lock:
                    self._active_generations = max(0, self._active_generations - 1)
                    if self._active_generations == 0:
                        self._active_started_at = None

        if audio.size == 0:
            raise RuntimeError("Synthesis produced empty audio")
        try:
            return self._encode_audio(audio, fmt)
        finally:
            del audio
            gc.collect()

    def _note_success(self) -> None:
        self._consecutive_timeouts = 0

    def _note_timeout(self, kind: str) -> None:
        self._consecutive_timeouts += 1
        logger.error(
            "TTS %s timeout consecutive=%s rss_mb=%s",
            kind,
            self._consecutive_timeouts,
            rss_mb(),
        )
        if self._consecutive_timeouts >= 2:
            self._mark_unhealthy_and_exit("repeated timeouts")

    async def generate(
        self,
        text: str,
        voice: str,
        speed: float,
        fmt: str,
        timeout_seconds: float,
    ) -> bytes:
        """Generate audio with concurrency limiting and timeout protection."""
        queue_wait_started = time.perf_counter()
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            self._note_timeout("queue")
            raise TimeoutError("Timed out waiting for a free TTS worker") from exc

        queue_ms = int((time.perf_counter() - queue_wait_started) * 1000)
        loop = asyncio.get_running_loop()
        remaining = max(0.1, timeout_seconds - (time.perf_counter() - queue_wait_started))
        future = loop.run_in_executor(
            self._executor,
            self.generate_sync,
            text,
            voice,
            speed,
            fmt,
        )

        release_on_exit = True
        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=remaining)
            self._note_success()
            if queue_ms > 50:
                logger.info("TTS queue wait ms=%s rss_mb=%s", queue_ms, rss_mb())
            return result
        except asyncio.TimeoutError as exc:
            # Keep the slot occupied until the worker finishes so RAM stays bounded.
            release_on_exit = False
            future.add_done_callback(lambda _f: self._semaphore.release())
            self._note_timeout("generation")
            raise TimeoutError("TTS generation timed out") from exc
        finally:
            if release_on_exit:
                self._semaphore.release()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._ready = False
        self._kokoro = None
