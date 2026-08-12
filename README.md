# Kokoro TTS API

Self-hosted [Kokoro](https://github.com/hexgrad/kokoro) text-to-speech API for
**Great Big World**, deployed as a standalone Railway service.

Production-ready FastAPI service designed for **Railway**, **CPU-only ONNX**,
**8 vCPU / 8 GB RAM** (typical RSS ~1.5–2.5 GB, well under the plan cap):

- One shared Kokoro ONNX session loaded at startup (no PyTorch)
- Single Uvicorn worker (no duplicated model RAM)
- Single in-flight generation by default (ONNX session is not thread-safe)
- Disk audio cache with SHA-256 keys
- Optional Bearer API key auth
- WAV + MP3 output (MP3 default)
- Process exits after a wedged/unhealthy engine so Railway restarts instead of serving 503 forever

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

`GET /warmup` is an alias of `/health` for keep-warm pings.

### Important latency note

`POST /tts` waits until the **entire** audio file is generated, then returns bytes.
There is no HTTP audio streaming. Clients should send **short segments** (1–3 sentences)
and start playback as soon as the first response arrives, synthesizing later segments
in parallel. Server disk cache (`X-TTS-Cache: HIT`) makes repeats near-instant.

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
- Kokoro ONNX weights (`kokoro-v1.0.onnx` + `voices-v1.0.bin`)

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
# From the Great Big World repository root:
cd tts
python3.11 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

mkdir -p /tmp/kokoro-models
curl -fsSL -o /tmp/kokoro-models/kokoro-v1.0.onnx \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -fsSL -o /tmp/kokoro-models/voices-v1.0.bin \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

cp .env.example .env
export $(grep -v '^#' .env | xargs)
export MODEL_PATH=/tmp/kokoro-models/kokoro-v1.0.onnx
export VOICES_PATH=/tmp/kokoro-models/voices-v1.0.bin

uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### Docker (local)

```bash
docker build -t kokoro-tts-api .
docker run --rm -p 8000:8000 \
  -e MAX_CONCURRENT_TTS=1 \
  -e CACHE_DIR=/app/cache \
  -v kokoro-cache:/app/cache \
  kokoro-tts-api
```

---

## Deploy on Railway

Production runs from the standalone TTS repo
([WrenchDevelops/GREATBIGWOLRD-TTS](https://github.com/WrenchDevelops/GREATBIGWOLRD-TTS)):
**Root Directory empty**, `Dockerfile` at the repo root.

The same files also live in the Great Big World monorepo under `tts/` if you deploy
from there instead (set **Root Directory** to `tts`).

1. Push this service to GitHub.
2. In Railway: **New Project → Deploy from GitHub repo** (or add a service).
3. Leave Root Directory empty for the standalone repo (or `tts` for the monorepo).
4. Railway uses `Dockerfile` and `railway.json`.
5. Set environment variables (below). Keep `MAX_CONCURRENT_TTS=1`.
6. Optional but recommended: add a **persistent volume** mounted at `/app/cache`.
7. Deploy. Cold start includes model load; healthcheck start period is generous.

The process listens on `0.0.0.0:$PORT` with **one worker**.

If `/health` returns 503 after a successful deploy, the replica is unhealthy and
will exit so Railway restarts it. Persistent 503s on the old PyTorch image meant
the process was wedged at the 8 GB cap and the app fell back to device TTS.

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
| `MAX_CONCURRENT_TTS` | `1` | In-flight generations (keep at 1) |
| `ONNX_NUM_THREADS` | `4` | ONNX Runtime intra-op threads (`TORCH_NUM_THREADS` still accepted) |
| `REQUEST_TIMEOUT_SECONDS` | `120` | Queue + generation timeout |
| `CACHE_ENABLED` | `true` | Enable disk cache |
| `CACHE_DIR` | `/app/cache` | Cache directory |
| `CACHE_MAX_BYTES` | `536870912` | ~512 MB cache budget |
| `LOG_LEVEL` | `INFO` | Logging level |
| `MODEL_PATH` | `/models/kokoro-v1.0.onnx` | ONNX model path |
| `VOICES_PATH` | `/models/voices-v1.0.bin` | Voice pack path |

### Recommended for 8 vCPU / 8 GB

```bash
MAX_CONCURRENT_TTS=1
ONNX_NUM_THREADS=4
CACHE_ENABLED=true
CACHE_DIR=/app/cache
CACHE_MAX_BYTES=536870912
DEFAULT_VOICE=af_heart
```

Why **ONNX instead of PyTorch**?

- PyTorch + spaCy + two Kokoro pipelines idle around several GB and spike over 8 GB during inference.
- The same Kokoro-82M voice via ONNX Runtime typically sits around 1.5–2.5 GB RSS.
- When the engine wedges, the process **exits** so Railway replaces the replica instead of returning 503 forever (which made the app fall back to device TTS).

Why **1 concurrent job**?

- One shared ONNX session; overlapping `Run()` is not safe.
- A threading lock serializes synthesis even if you raise the limit.
- Spend CPU on one high-quality job (`ONNX_NUM_THREADS=4`) instead of contending jobs.

**Do not** raise Uvicorn/Gunicorn `--workers` above 1 — each worker would reload the model.

If Railway still has `MAX_CONCURRENT_TTS=2` or a 2 GB `CACHE_MAX_BYTES` set, set them to the values above. After deploy, **restart** the service once if play is still on the device voice.

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
CACHE_MAX_BYTES=536870912
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
  tts.py       Shared ONNX session + semaphore + restart-on-unhealthy
  cache.py     SHA-256 disk cache + size eviction
  config.py    Environment configuration
  models.py    Request validation + voice catalog
```

Startup flow:

1. Configure ONNX thread limits
2. Load one Kokoro ONNX session on CPU
3. Load the voice pack
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
- ONNX export used at runtime: [kokoro-onnx model-files-v1.0](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0).
- The Docker image pre-downloads ONNX weights for reliable deploys.
