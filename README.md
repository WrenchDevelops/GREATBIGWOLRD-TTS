# Kokoro TTS API

Self-hosted [Kokoro](https://github.com/hexgrad/kokoro) text-to-speech API for Great Big World.

Production-ready FastAPI service designed for **Railway**, **CPU-only**,
**8 vCPU / 8 GB RAM**:

- One shared Kokoro model loaded at startup
- Single Uvicorn worker (no duplicated model RAM)
- Configurable internal concurrency (default **2**)
- Disk audio cache with SHA-256 keys
- Optional Bearer API key auth
- WAV + MP3 output (MP3 default)

Default voice: **`af_heart`** (high-quality American English).

---

## Endpoints

### `GET /health`

```json
{
  "status": "ok",
  "model_loaded": true,
  "default_voice": "af_heart",
  "ready": true
}
```

### `GET /voices`

Returns the Kokoro voice catalog and metadata. Requires auth when `API_KEY` is set.

### `POST /tts`

```json
{
  "text": "Hello, this is a test.",
  "voice": "af_heart",
  "speed": 1.0,
  "format": "mp3"
}
```

Returns audio bytes with:

| Header | Example |
|---|---|
| `Content-Type` | `audio/mpeg` or `audio/wav` |
| `X-TTS-Cache` | `HIT` / `MISS` |
| `X-TTS-Generation-Time` | milliseconds |
| `X-TTS-Voice` | `af_heart` |

---

## Local development

### Prerequisites

- Python 3.11+
- [`espeak-ng`](https://github.com/espeak-ng/espeak-ng)
- [`ffmpeg`](https://ffmpeg.org/)
- CPU-only PyTorch

macOS:

```bash
brew install espeak ffmpeg
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y espeak-ng ffmpeg libsndfile1
```

### Setup

```bash
cd GREATBIGWOLRD-TTS
python3.11 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install --index-url https://download.pytorch.org/whl/cpu torch==2.6.0
pip install -r requirements.txt

cp .env.example .env
export $(grep -v '^#' .env | xargs)

# First run downloads Kokoro-82M weights (~300MB) into the Hugging Face cache.
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### Docker (local)

```bash
docker build -t kokoro-tts-api .
docker run --rm -p 8000:8000 \
  -e MAX_CONCURRENT_TTS=2 \
  -e CACHE_DIR=/app/cache \
  -v kokoro-cache:/app/cache \
  kokoro-tts-api
```

---

## Deploy on Railway

1. Connect this GitHub repo in Railway: **New Project → Deploy from GitHub repo**.
2. Railway uses the root `Dockerfile` / `railway.json`.
3. Set environment variables (below).
4. Optional but recommended: add a **persistent volume** mounted at `/app/cache`.
5. Deploy. Cold start includes model load; healthcheck start period is generous.

The process listens on `0.0.0.0:$PORT` with **one worker**.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Listen port (Railway sets this) |
| `API_KEY` | _(empty)_ | If set, require `Authorization: Bearer …` |
| `ALLOWED_ORIGINS` | _(empty)_ | Comma-separated CORS origins, or `*`. Empty = CORS off |
| `DEFAULT_VOICE` | `af_heart` | Default Kokoro voice |
| `DEFAULT_FORMAT` | `mp3` | `mp3` or `wav` |
| `MAX_TEXT_LENGTH` | `2000` | Max characters per request |
| `MAX_CONCURRENT_TTS` | `2` | Simultaneous generations |
| `TORCH_NUM_THREADS` | `3` | PyTorch intra-op threads |
| `TORCH_NUM_INTEROP_THREADS` | `1` | PyTorch inter-op threads |
| `REQUEST_TIMEOUT_SECONDS` | `120` | Queue + generation timeout |
| `CACHE_ENABLED` | `true` | Enable disk cache |
| `CACHE_DIR` | `/app/cache` | Cache directory |
| `CACHE_MAX_BYTES` | `2147483648` | ~2 GB cache budget |
| `LOG_LEVEL` | `INFO` | Logging level |
| `MODEL_REPO` | `hexgrad/Kokoro-82M` | Hugging Face model repo |

### Recommended for 8 vCPU / 8 GB

```bash
MAX_CONCURRENT_TTS=2
TORCH_NUM_THREADS=3
CACHE_ENABLED=true
CACHE_DIR=/app/cache
CACHE_MAX_BYTES=2147483648
DEFAULT_VOICE=af_heart
```

Why **2 concurrent jobs**?

- Kokoro-82M is small, but CPU inference + audio encode still uses memory and cores.
- Two jobs × ~3 torch threads keeps utilization high without RAM spikes.
- Prefer voice quality and stability over peak throughput.
- You can try `MAX_CONCURRENT_TTS=3` if memory stays comfortably under ~6 GB; avoid 4+ on 8 GB.

**Do not** raise Uvicorn/Gunicorn `--workers` above 1 — each worker would reload the model.

---

## Testing

### Health

```bash
curl -s https://YOUR-SERVICE.up.railway.app/health | jq
```

### List voices

```bash
curl -s https://YOUR-SERVICE.up.railway.app/voices \
  -H "Authorization: Bearer YOUR_API_KEY" | jq
```

### Generate speech (MP3)

```bash
curl -X POST https://YOUR-SERVICE.up.railway.app/tts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "text": "Hello, this is a test of Kokoro TTS.",
    "voice": "af_heart",
    "speed": 1.0,
    "format": "mp3"
  }' \
  --output speech.mp3
```

### Generate WAV

```bash
curl -X POST https://YOUR-SERVICE.up.railway.app/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello without an API key when API_KEY is unset.",
    "voice": "af_bella",
    "format": "wav"
  }' \
  --output speech.wav
```

### Change voices

1. Call `GET /voices` and pick an `id`.
2. Pass it as `"voice": "am_michael"` (or any catalog id) in `POST /tts`.
3. Or set `DEFAULT_VOICE=af_bella` for the server default.

English voices (`af_*`, `am_*`, `bf_*`, `bm_*`) are the primary production path.

### Enable API key auth

Set on Railway:

```bash
API_KEY=super-secret-value
```

Then every `/voices` and `/tts` request must include:

```http
Authorization: Bearer super-secret-value
```

If `API_KEY` is unset, auth is disabled.

### Persistent caching

1. Create a Railway volume.
2. Mount it at `/app/cache`.
3. Set:

```bash
CACHE_ENABLED=true
CACHE_DIR=/app/cache
CACHE_MAX_BYTES=2147483648
```

Cache key:

```text
SHA256(text + "|" + voice + "|" + speed + "|" + format)
```

Identical requests return `X-TTS-Cache: HIT` without regenerating.

If the volume is missing or not writable, the API still runs and simply skips caching.

---

## JavaScript client

```javascript
const response = await fetch("https://YOUR-SERVICE.up.railway.app/tts", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": "Bearer YOUR_API_KEY"
  },
  body: JSON.stringify({
    text: "Hello from my app!",
    voice: "af_heart",
    speed: 1.0,
    format: "mp3"
  })
});

if (!response.ok) {
  throw new Error(`TTS failed: ${response.status}`);
}

const audioBlob = await response.blob();

// Play in the browser
const audioUrl = URL.createObjectURL(audioBlob);
const audio = new Audio(audioUrl);
audio.play();

// Optional cleanup after playback
audio.addEventListener("ended", () => URL.revokeObjectURL(audioUrl));
```

HTML example:

```html
<button id="speak">Speak</button>
<script>
document.getElementById("speak").onclick = async () => {
  const response = await fetch("https://YOUR-SERVICE.up.railway.app/tts", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer YOUR_API_KEY"
    },
    body: JSON.stringify({
      text: "Welcome to Great Big World.",
      voice: "af_heart",
      format: "mp3"
    })
  });
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  new Audio(url).play();
};
</script>
```

---

## Architecture

```text
app/
  main.py      FastAPI routes, auth, CORS, response headers
  tts.py       Shared KModel + language pipelines + semaphore
  cache.py     SHA-256 disk cache + size eviction
  config.py    Environment configuration
  models.py    Request validation + voice catalog
```

Startup flow:

1. Configure CPU thread limits
2. Load one `KModel` on CPU
3. Create American/British `KPipeline`s reusing that model
4. Verify `DEFAULT_VOICE` and warm up synthesis
5. Serve requests forever without reloading weights

---

## Security notes

- Optional `API_KEY` Bearer auth
- Max text length
- Speed bounds
- Request timeout
- Concurrent generation cap
- CORS off unless `ALLOWED_ORIGINS` is set
- Full user text is **not** written to logs (only character counts)

---

## License notes

- This service code: use freely in your project.
- Kokoro-82M model weights: Apache-2.0 ([hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)).
- The Docker image pre-downloads model weights for reliable deploys.
