"""Deterministic disk cache for generated audio."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("kokoro_tts.cache")


class AudioCache:
    """SHA256-keyed audio cache with optional size-based eviction."""

    def __init__(self, cache_dir: str, max_bytes: int, enabled: bool = True) -> None:
        self.enabled = enabled
        self.max_bytes = max(0, max_bytes)
        self.cache_dir = Path(cache_dir)
        self._lock = threading.Lock()

        if not self.enabled:
            logger.info("Audio cache disabled")
            return

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            # Verify write access without leaving debris.
            probe = self.cache_dir / ".write_probe"
            probe.write_bytes(b"ok")
            probe.unlink(missing_ok=True)
            logger.info(
                "Audio cache ready dir=%s max_bytes=%s",
                self.cache_dir,
                self.max_bytes,
            )
        except OSError as exc:
            # Persistent volumes are optional; fall back to generation-only mode.
            self.enabled = False
            logger.warning("Audio cache unavailable (%s); continuing without cache", exc)

    @staticmethod
    def make_key(text: str, voice: str, speed: float, fmt: str) -> str:
        payload = f"{text}|{voice}|{speed:.4f}|{fmt.lower()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _path_for(self, key: str, fmt: str) -> Path:
        return self.cache_dir / f"{key}.{fmt.lower()}"

    def get(self, key: str, fmt: str) -> Optional[bytes]:
        if not self.enabled:
            return None

        path = self._path_for(key, fmt)
        try:
            if not path.is_file():
                return None
            data = path.read_bytes()
            # Refresh mtime for LRU-ish eviction.
            os.utime(path, None)
            return data
        except OSError as exc:
            logger.warning("Cache read failed key=%s error=%s", key[:12], exc)
            return None

    def put(self, key: str, fmt: str, data: bytes) -> None:
        if not self.enabled or not data:
            return

        path = self._path_for(key, fmt)
        tmp_path = path.with_suffix(path.suffix + ".tmp")

        with self._lock:
            try:
                tmp_path.write_bytes(data)
                os.replace(tmp_path, path)
                self._enforce_size_limit()
            except OSError as exc:
                logger.warning("Cache write failed key=%s error=%s", key[:12], exc)
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _enforce_size_limit(self) -> None:
        if self.max_bytes <= 0:
            return

        entries: list[tuple[float, Path, int]] = []
        total = 0
        for path in self.cache_dir.iterdir():
            if not path.is_file():
                continue
            if path.name.startswith(".") or path.suffix.endswith(".tmp"):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            total += stat.st_size
            entries.append((stat.st_mtime, path, stat.st_size))

        if total <= self.max_bytes:
            return

        entries.sort(key=lambda item: item[0])  # oldest first
        removed = 0
        for _, path, size in entries:
            if total <= self.max_bytes:
                break
            try:
                path.unlink(missing_ok=True)
                total -= size
                removed += 1
            except OSError:
                continue

        if removed:
            logger.info(
                "Cache cleanup removed=%s bytes_now=%s max_bytes=%s",
                removed,
                total,
                self.max_bytes,
            )

    def stats(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "files": 0, "bytes": 0}

        files = 0
        total = 0
        try:
            for path in self.cache_dir.iterdir():
                if path.is_file() and not path.name.startswith("."):
                    files += 1
                    total += path.stat().st_size
        except OSError:
            pass
        return {
            "enabled": True,
            "dir": str(self.cache_dir),
            "files": files,
            "bytes": total,
            "max_bytes": self.max_bytes,
            "updated_at": time.time(),
        }
