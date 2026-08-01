import re
import asyncio
import threading

import numpy as np
import sounddevice as sd
import torch
from scipy import signal
from transformers import VitsModel, AutoTokenizer
from langdetect import detect, DetectorFactory

# Make language detection deterministic across runs.
DetectorFactory.seed = 0

# ---------------------------------------------------------------------------
# VOICE CONFIG  (Meta MMS-TTS — fully offline, self-hosted)
# ---------------------------------------------------------------------------
# Milo speaks with Meta's MMS-TTS VITS models, loaded directly into the server.
# No internet, no API key. We auto-detect the reply's language and load the
# matching model on first use (then keep it cached in memory).
#
# Models are downloaded once from the Hugging Face Hub to the local HF cache,
# after which everything runs offline. Each model is ~145 MB.
# ---------------------------------------------------------------------------
MODEL_MAP = {
    "en": "facebook/mms-tts-eng",  # English
    "hi": "facebook/mms-tts-hin",  # Hindi
    "mr": "facebook/mms-tts-mar",  # Marathi
}
DEFAULT_LANG = "en"

# Devanagari Unicode block — used to tell Indian-language replies from English.
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")

# In-memory cache of loaded (model, tokenizer) per language, so each model is
# loaded from disk only once. A lock keeps the lazy load thread-safe (playback
# runs in worker threads).
_models = {}
_load_lock = threading.Lock()


def detect_language(text: str) -> str:
    """
    Decide which voice language to use for a reply. Milo only replies in
    English, Hindi, or Marathi, so detection stays simple and robust:
      - Any Devanagari script  -> Hindi or Marathi (langdetect picks between them)
      - Otherwise              -> English
    """
    if _DEVANAGARI_RE.search(text):
        try:
            lang = detect(text)
        except Exception:
            lang = "hi"
        return "mr" if lang == "mr" else "hi"
    return "en"


def _get_model(lang: str):
    """Lazily load and cache the (model, tokenizer) for a language."""
    if lang not in MODEL_MAP:
        lang = DEFAULT_LANG
    if lang not in _models:
        with _load_lock:
            if lang not in _models:  # re-check inside the lock
                model_id = MODEL_MAP[lang]
                print(f"[TTS] Loading MMS model {model_id} ...")
                model = VitsModel.from_pretrained(model_id)
                model.eval()
                tokenizer = AutoTokenizer.from_pretrained(model_id)
                _models[lang] = (model, tokenizer)
                print(f"[TTS] Loaded {model_id}.")
    return _models[lang]


def preload_models():
    """Optionally warm up all models at startup to avoid first-reply latency."""
    for lang in MODEL_MAP:
        _get_model(lang)


def _synthesize_and_play(text: str, lang: str):
    """Synthesize `text` with the MMS model for `lang` and play it (blocking)."""
    model, tokenizer = _get_model(lang)
    inputs = tokenizer(text, return_tensors="pt")
    with torch.no_grad():
        waveform = model(**inputs).waveform[0].cpu().numpy()

    sample_rate = model.config.sampling_rate  # MMS models are 16 kHz
    pcm = np.clip(waveform, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)

    sd.play(pcm, samplerate=sample_rate)
    sd.wait()  # block until playback finishes (runs off the event loop, see speak())


async def speak(text: str):
    """
    Synthesize `text` in the detected language and play it aloud.
    The heavy synthesis + blocking playback run in a worker thread so they
    never stall the FastAPI event loop.
    """
    text = (text or "").strip()
    if not text:
        return

    lang = detect_language(text)
    print(f"[TTS] lang={lang} model={MODEL_MAP.get(lang, MODEL_MAP[DEFAULT_LANG])} :: {text[:60]}...")

    try:
        await asyncio.to_thread(_synthesize_and_play, text, lang)
        print("[TTS] Playback finished.")
    except Exception as e:
        print(f"[TTS] Error during synthesis/playback: {e}")


async def generate_audio(text: str, output_filepath: str = ""):
    """
    Entrypoint called by app.py. `output_filepath` is ignored — audio is played
    directly on the host rather than written to disk.
    """
    await speak(text)


# ---------------------------------------------------------------------------
# Streaming helpers for the real-time WebSocket loop.
# Instead of playing audio on the backend, we synthesize raw PCM and hand it to
# the frontend to play (so the browser's echo cancellation can work and the user
# can interrupt).
# ---------------------------------------------------------------------------

# Sentence boundaries: Latin (.!?) plus the Devanagari danda (।).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+")


def split_sentences(text: str):
    """Split text into sentence-sized chunks for incremental synthesis."""
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    return parts or [text]


# ---------------------------------------------------------------------------
# Emotion -> prosody.  MMS is a flat single-speaker model, so we make it
# emotional by (a) tuning its own intonation params and (b) light DSP:
#   - noise_scale / noise_scale_duration : how animated the model's intonation is
#   - resample factor : >1 = faster + higher/brighter, <1 = slower + lower/heavier
#                       (pitch and tempo move together, like real emotional speech)
#   - gain : loudness / energy
# Keep the numbers subtle so it stays natural (no chipmunk).
# ---------------------------------------------------------------------------
EMOTION_PROSODY = {
    "neutral":   {"resample": 1.00, "noise": 0.667, "ndur": 0.80, "gain": 1.00},
    "happy":     {"resample": 1.06, "noise": 0.85,  "ndur": 0.90, "gain": 1.06},
    "excited":   {"resample": 1.09, "noise": 0.95,  "ndur": 1.00, "gain": 1.12},
    "surprised": {"resample": 1.10, "noise": 0.95,  "ndur": 1.00, "gain": 1.12},
    "curious":   {"resample": 1.03, "noise": 0.85,  "ndur": 0.90, "gain": 1.03},
    "angry":     {"resample": 1.04, "noise": 0.80,  "ndur": 0.85, "gain": 1.20},
    "sad":       {"resample": 0.93, "noise": 0.55,  "ndur": 0.70, "gain": 0.85},
    "thinking":  {"resample": 0.97, "noise": 0.60,  "ndur": 0.80, "gain": 0.95},
}


# ---------------------------------------------------------------------------
# Voice styles.  MMS has one speaker per language, so "different voices" are
# pitch/character variations (plus an optional robotic ring-mod). A style sets a
# BASE pitch/tempo/energy that the per-emotion prosody then modulates around.
# ---------------------------------------------------------------------------
VOICE_STYLES = {
    "milo":   {"label": "Milo (default)", "pitch": 1.00, "gain": 1.00, "noise_bias": 0.00, "robotic": 0.0},
    "deep":   {"label": "Deep",           "pitch": 0.90, "gain": 1.02, "noise_bias": -0.05, "robotic": 0.0},
    "bright": {"label": "Bright",         "pitch": 1.12, "gain": 1.00, "noise_bias": 0.05, "robotic": 0.0},
    "calm":   {"label": "Calm",           "pitch": 0.96, "gain": 0.96, "noise_bias": -0.08, "robotic": 0.0},
    "robo":   {"label": "Robo",           "pitch": 1.04, "gain": 1.00, "noise_bias": 0.00, "robotic": 0.5},
}
DEFAULT_STYLE = "milo"


def list_voice_styles():
    """Return [{id, label}] for the UI dropdown."""
    return [{"id": k, "label": v["label"]} for k, v in VOICE_STYLES.items()]


def synthesize_pcm(text: str, lang: str = None, emotion: str = "neutral", style: str = DEFAULT_STYLE):
    """
    Synthesize `text` with the chosen voice style + emotion-driven prosody, and
    return (pcm_int16_bytes, sample_rate) WITHOUT playing.
    """
    text = (text or "").strip()
    if not text:
        return b"", 0

    if lang is None:
        lang = detect_language(text)

    prosody = EMOTION_PROSODY.get((emotion or "neutral").lower(), EMOTION_PROSODY["neutral"])
    voice = VOICE_STYLES.get((style or DEFAULT_STYLE).lower(), VOICE_STYLES[DEFAULT_STYLE])

    model, tokenizer = _get_model(lang)
    # Model expressiveness = emotion animation, nudged by the voice style.
    model.noise_scale = max(0.1, prosody["noise"] + voice["noise_bias"])
    model.noise_scale_duration = prosody["ndur"]

    inputs = tokenizer(text, return_tensors="pt")
    with torch.no_grad():
        waveform = model(**inputs).waveform[0].cpu().numpy().astype(np.float32)

    sample_rate = model.config.sampling_rate

    # Pitch + tempo: emotion factor combined with the style's base pitch.
    factor = prosody["resample"] * voice["pitch"]
    if abs(factor - 1.0) > 1e-3:
        new_len = max(1, int(len(waveform) / factor))
        waveform = signal.resample(waveform, new_len).astype(np.float32)

    # Optional robotic timbre (subtle ring modulation).
    if voice["robotic"] > 0:
        t = np.arange(len(waveform)) / sample_rate
        carrier = np.sin(2 * np.pi * 75 * t).astype(np.float32)  # 75 Hz buzz
        waveform = waveform * (1.0 - voice["robotic"] + voice["robotic"] * (0.5 + 0.5 * carrier))

    waveform = waveform * (prosody["gain"] * voice["gain"])

    pcm = np.clip(waveform, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    return pcm.tobytes(), sample_rate
