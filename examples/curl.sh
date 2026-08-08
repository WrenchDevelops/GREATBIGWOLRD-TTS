#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
API_KEY="${API_KEY:-}"

auth_header=()
if [[ -n "${API_KEY}" ]]; then
  auth_header=(-H "Authorization: Bearer ${API_KEY}")
fi

echo "GET ${BASE_URL}/health"
curl -fsS "${BASE_URL}/health"
echo
echo

echo "GET ${BASE_URL}/voices"
curl -fsS "${BASE_URL}/voices" "${auth_header[@]}"
echo
echo

echo "POST ${BASE_URL}/tts -> speech.mp3"
curl -fsS -X POST "${BASE_URL}/tts" \
  -H "Content-Type: application/json" \
  "${auth_header[@]}" \
  -d '{
    "text": "Hello, this is a test of Kokoro TTS.",
    "voice": "af_heart",
    "speed": 1.0,
    "format": "mp3"
  }' \
  --output speech.mp3

echo "Wrote speech.mp3"
