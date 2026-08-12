# syntax=docker/dockerfile:1.7

FROM python:3.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    CUDA_VISIBLE_DEVICES="" \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=2 \
    PORT=8000 \
    MODEL_PATH=/models/kokoro-v1.0.onnx \
    VOICES_PATH=/models/voices-v1.0.bin

WORKDIR /app

# espeak-ng for G2P, ffmpeg for MP3, libsndfile for WAV, jemalloc to keep RSS down.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        espeak-ng \
        ffmpeg \
        libsndfile1 \
        libjemalloc2 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Path-agnostic preload so this works on amd64 and arm64.
ENV LD_PRELOAD=libjemalloc.so.2

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Pre-download ONNX weights (~310MB) + voice pack (~27MB) for reliable cold starts.
# GitHub release CDN often drops mid-transfer during Railway builds (curl exit 56).
# Resume (-C -), retry transient errors, and verify exact Content-Length bytes.
RUN mkdir -p /models \
    && download() { \
         dest="$1"; expect="$2"; url="$3"; \
         attempt=1; \
         while [ "$attempt" -le 10 ]; do \
           if [ -f "$dest" ]; then \
             size=$(wc -c < "$dest"); \
             if [ "$size" -eq "$expect" ]; then \
               echo "OK $dest ($size bytes)"; \
               return 0; \
             fi; \
             echo "Incomplete $dest ($size/$expect); resuming..."; \
           else \
             echo "Downloading $dest (attempt $attempt)..."; \
           fi; \
           if curl -L --fail --retry 5 --retry-all-errors --retry-delay 3 \
                --connect-timeout 30 --max-time 900 \
                -C - -o "$dest" "$url"; then \
             size=$(wc -c < "$dest"); \
             if [ "$size" -eq "$expect" ]; then \
               echo "OK $dest ($size bytes)"; \
               return 0; \
             fi; \
             echo "Size mismatch after curl: got $size expected $expect"; \
           else \
             echo "curl failed for $dest (exit $?)"; \
           fi; \
           attempt=$((attempt + 1)); \
           sleep $((attempt * 2)); \
         done; \
         echo "Failed to download $dest after retries"; \
         return 1; \
       } \
    && download /models/kokoro-v1.0.onnx 325532387 \
         https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx \
    && download /models/voices-v1.0.bin 28214398 \
         https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

COPY app ./app

RUN mkdir -p /app/cache \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /models

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Single worker: one ONNX session in RAM. Internal semaphore controls concurrency.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --timeout-keep-alive 75 --log-level info"]
