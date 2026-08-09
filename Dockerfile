# syntax=docker/dockerfile:1.7

FROM python:3.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    CUDA_VISIBLE_DEVICES="" \
    HF_HOME=/models/huggingface \
    HUGGINGFACE_HUB_CACHE=/models/huggingface \
    TORCH_HOME=/models/torch \
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    OPENBLAS_NUM_THREADS=4 \
    NUMEXPR_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=2 \
    PORT=8000

WORKDIR /app

# System deps: espeak-ng for Kokoro English OOD fallback / non-English G2P,
# ffmpeg for MP3 encoding, libsndfile for soundfile.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        espeak-ng \
        ffmpeg \
        libsndfile1 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first (no CUDA/cuDNN).
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu \
        torch==2.6.0

COPY requirements.txt .
RUN pip install -r requirements.txt \
    && python -m spacy download en_core_web_sm

# Pre-download Kokoro-82M weights (Apache-2.0) for reliable cold starts.
RUN mkdir -p /models/huggingface \
    && python - <<'PY'
from huggingface_hub import snapshot_download

snapshot_download(repo_id="hexgrad/Kokoro-82M")
print("Kokoro model cached")
PY

COPY app ./app

RUN mkdir -p /app/cache \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /models

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Single worker: one shared model in RAM. Internal semaphore controls concurrency.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --timeout-keep-alive 75 --log-level info"]
