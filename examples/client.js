/**
 * Browser / Node 18+ example for the Kokoro TTS API.
 *
 * Replace YOUR-SERVICE and YOUR_API_KEY before running.
 */

const TTS_URL = "https://YOUR-SERVICE.up.railway.app/tts";
const API_KEY = "YOUR_API_KEY"; // leave empty if API_KEY is not configured

export async function synthesizeSpeech({
  text,
  voice = "af_heart",
  speed = 1.0,
  format = "mp3",
} = {}) {
  const headers = {
    "Content-Type": "application/json",
  };
  if (API_KEY && API_KEY !== "YOUR_API_KEY") {
    headers.Authorization = `Bearer ${API_KEY}`;
  }

  const response = await fetch(TTS_URL, {
    method: "POST",
    headers,
    body: JSON.stringify({ text, voice, speed, format }),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`TTS failed (${response.status}): ${detail}`);
  }

  console.log("X-TTS-Cache:", response.headers.get("X-TTS-Cache"));
  console.log("X-TTS-Generation-Time:", response.headers.get("X-TTS-Generation-Time"));
  console.log("X-TTS-Voice:", response.headers.get("X-TTS-Voice"));

  return response.blob();
}

export async function playSpeech(options) {
  const audioBlob = await synthesizeSpeech(options);
  const audioUrl = URL.createObjectURL(audioBlob);
  const audio = new Audio(audioUrl);
  await audio.play();
  audio.addEventListener("ended", () => URL.revokeObjectURL(audioUrl));
  return audio;
}

// Example:
// await playSpeech({ text: "Hello from my app!", voice: "af_heart" });
