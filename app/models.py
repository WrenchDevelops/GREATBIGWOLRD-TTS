"""Pydantic request/response models and voice catalog metadata."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

AudioFormat = Literal["mp3", "wav"]


# High-quality English voices are listed first. Metadata mirrors Kokoro-82M docs.
VOICE_CATALOG: list[dict] = [
    # American English — Female
    {"id": "af_heart", "name": "Heart", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "A", "traits": "high quality"},
    {"id": "af_bella", "name": "Bella", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "A-", "traits": "expressive"},
    {"id": "af_nicole", "name": "Nicole", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "B-", "traits": "podcast"},
    {"id": "af_aoede", "name": "Aoede", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "C+", "traits": None},
    {"id": "af_kore", "name": "Kore", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "C+", "traits": None},
    {"id": "af_sarah", "name": "Sarah", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "C+", "traits": None},
    {"id": "af_alloy", "name": "Alloy", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "C", "traits": None},
    {"id": "af_nova", "name": "Nova", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "C", "traits": None},
    {"id": "af_sky", "name": "Sky", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "C-", "traits": None},
    {"id": "af_jessica", "name": "Jessica", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "D", "traits": None},
    {"id": "af_river", "name": "River", "language": "en-us", "lang_code": "a", "gender": "female", "grade": "D", "traits": None},
    # American English — Male
    {"id": "am_fenrir", "name": "Fenrir", "language": "en-us", "lang_code": "a", "gender": "male", "grade": "C+", "traits": None},
    {"id": "am_michael", "name": "Michael", "language": "en-us", "lang_code": "a", "gender": "male", "grade": "C+", "traits": None},
    {"id": "am_puck", "name": "Puck", "language": "en-us", "lang_code": "a", "gender": "male", "grade": "C+", "traits": None},
    {"id": "am_echo", "name": "Echo", "language": "en-us", "lang_code": "a", "gender": "male", "grade": "D", "traits": None},
    {"id": "am_eric", "name": "Eric", "language": "en-us", "lang_code": "a", "gender": "male", "grade": "D", "traits": None},
    {"id": "am_liam", "name": "Liam", "language": "en-us", "lang_code": "a", "gender": "male", "grade": "D", "traits": None},
    {"id": "am_onyx", "name": "Onyx", "language": "en-us", "lang_code": "a", "gender": "male", "grade": "D", "traits": None},
    {"id": "am_santa", "name": "Santa", "language": "en-us", "lang_code": "a", "gender": "male", "grade": "D-", "traits": None},
    {"id": "am_adam", "name": "Adam", "language": "en-us", "lang_code": "a", "gender": "male", "grade": "F+", "traits": None},
    # British English — Female
    {"id": "bf_emma", "name": "Emma", "language": "en-gb", "lang_code": "b", "gender": "female", "grade": "B-", "traits": None},
    {"id": "bf_isabella", "name": "Isabella", "language": "en-gb", "lang_code": "b", "gender": "female", "grade": "C", "traits": None},
    {"id": "bf_alice", "name": "Alice", "language": "en-gb", "lang_code": "b", "gender": "female", "grade": "D", "traits": None},
    {"id": "bf_lily", "name": "Lily", "language": "en-gb", "lang_code": "b", "gender": "female", "grade": "D", "traits": None},
    # British English — Male
    {"id": "bm_george", "name": "George", "language": "en-gb", "lang_code": "b", "gender": "male", "grade": "C", "traits": None},
    {"id": "bm_fable", "name": "Fable", "language": "en-gb", "lang_code": "b", "gender": "male", "grade": "C", "traits": None},
    {"id": "bm_daniel", "name": "Daniel", "language": "en-gb", "lang_code": "b", "gender": "male", "grade": "D", "traits": None},
    {"id": "bm_lewis", "name": "Lewis", "language": "en-gb", "lang_code": "b", "gender": "male", "grade": "D+", "traits": None},
    # Spanish
    {"id": "ef_dora", "name": "Dora", "language": "es", "lang_code": "e", "gender": "female", "grade": None, "traits": None},
    {"id": "em_alex", "name": "Alex", "language": "es", "lang_code": "e", "gender": "male", "grade": None, "traits": None},
    {"id": "em_santa", "name": "Santa", "language": "es", "lang_code": "e", "gender": "male", "grade": None, "traits": None},
    # French
    {"id": "ff_siwis", "name": "Siwis", "language": "fr-fr", "lang_code": "f", "gender": "female", "grade": None, "traits": None},
    # Hindi
    {"id": "hf_alpha", "name": "Alpha", "language": "hi", "lang_code": "h", "gender": "female", "grade": None, "traits": None},
    {"id": "hf_beta", "name": "Beta", "language": "hi", "lang_code": "h", "gender": "female", "grade": None, "traits": None},
    {"id": "hm_omega", "name": "Omega", "language": "hi", "lang_code": "h", "gender": "male", "grade": None, "traits": None},
    {"id": "hm_psi", "name": "Psi", "language": "hi", "lang_code": "h", "gender": "male", "grade": None, "traits": None},
    # Italian
    {"id": "if_sara", "name": "Sara", "language": "it", "lang_code": "i", "gender": "female", "grade": None, "traits": None},
    {"id": "im_nicola", "name": "Nicola", "language": "it", "lang_code": "i", "gender": "male", "grade": None, "traits": None},
    # Japanese (requires misaki[ja] for best quality; still listed for API discovery)
    {"id": "jf_alpha", "name": "Alpha", "language": "ja", "lang_code": "j", "gender": "female", "grade": None, "traits": None},
    {"id": "jf_gongitsune", "name": "Gongitsune", "language": "ja", "lang_code": "j", "gender": "female", "grade": None, "traits": None},
    {"id": "jf_nezumi", "name": "Nezumi", "language": "ja", "lang_code": "j", "gender": "female", "grade": None, "traits": None},
    {"id": "jf_tebukuro", "name": "Tebukuro", "language": "ja", "lang_code": "j", "gender": "female", "grade": None, "traits": None},
    {"id": "jm_kumo", "name": "Kumo", "language": "ja", "lang_code": "j", "gender": "male", "grade": None, "traits": None},
    # Brazilian Portuguese
    {"id": "pf_dora", "name": "Dora", "language": "pt-br", "lang_code": "p", "gender": "female", "grade": None, "traits": None},
    {"id": "pm_alex", "name": "Alex", "language": "pt-br", "lang_code": "p", "gender": "male", "grade": None, "traits": None},
    {"id": "pm_santa", "name": "Santa", "language": "pt-br", "lang_code": "p", "gender": "male", "grade": None, "traits": None},
    # Mandarin Chinese (requires misaki[zh] for best quality)
    {"id": "zf_xiaobei", "name": "Xiaobei", "language": "zh", "lang_code": "z", "gender": "female", "grade": None, "traits": None},
    {"id": "zf_xiaoni", "name": "Xiaoni", "language": "zh", "lang_code": "z", "gender": "female", "grade": None, "traits": None},
    {"id": "zf_xiaoxiao", "name": "Xiaoxiao", "language": "zh", "lang_code": "z", "gender": "female", "grade": None, "traits": None},
    {"id": "zf_xiaoyi", "name": "Xiaoyi", "language": "zh", "lang_code": "z", "gender": "female", "grade": None, "traits": None},
    {"id": "zm_yunjian", "name": "Yunjian", "language": "zh", "lang_code": "z", "gender": "male", "grade": None, "traits": None},
    {"id": "zm_yunxi", "name": "Yunxi", "language": "zh", "lang_code": "z", "gender": "male", "grade": None, "traits": None},
    {"id": "zm_yunxia", "name": "Yunxia", "language": "zh", "lang_code": "z", "gender": "male", "grade": None, "traits": None},
    {"id": "zm_yunyang", "name": "Yunyang", "language": "zh", "lang_code": "z", "gender": "male", "grade": None, "traits": None},
]

VOICE_BY_ID: dict[str, dict] = {voice["id"]: voice for voice in VOICE_CATALOG}
SUPPORTED_VOICES: set[str] = set(VOICE_BY_ID.keys())

# kokoro-onnx / espeak-ng language tags keyed by Kokoro lang_code.
_ESPEAK_LANG = {
    "a": "en-us",
    "b": "en-gb",
    "e": "es",
    "f": "fr-fr",
    "h": "hi",
    "i": "it",
    "j": "ja",
    "p": "pt-br",
    "z": "cmn",
}


def espeak_lang_for_voice(voice: str) -> str:
    meta = VOICE_BY_ID.get(voice)
    if meta is None:
        return "en-us"
    return _ESPEAK_LANG.get(meta["lang_code"], meta.get("language") or "en-us")


class TTSRequest(BaseModel):
    """JSON body for POST /tts."""

    text: str = Field(..., min_length=1, description="Text to synthesize")
    voice: str = Field(default="af_heart", description="Kokoro voice id")
    speed: float = Field(default=1.0, description="Speech speed multiplier")
    format: AudioFormat = Field(default="mp3", description="Output audio format")

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must not be empty")
        return cleaned

    @field_validator("voice")
    @classmethod
    def normalize_voice(cls, value: str) -> str:
        voice = value.strip().lower()
        if not voice:
            raise ValueError("voice must not be empty")
        return voice

    @field_validator("format")
    @classmethod
    def normalize_format(cls, value: str) -> str:
        return value.strip().lower()


class VoiceInfo(BaseModel):
    id: str
    name: str
    language: str
    lang_code: str
    gender: str
    grade: Optional[str] = None
    traits: Optional[str] = None
    default: bool = False


class VoicesResponse(BaseModel):
    default_voice: str
    count: int
    voices: list[VoiceInfo]


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool = True
    default_voice: str
    ready: bool = True
