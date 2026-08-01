import os
import io
import base64
import threading

from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# SPEECH-TO-TEXT  (OpenAI Whisper large-v3 via faster-whisper, self-hosted)
# ---------------------------------------------------------------------------
# High-quality multilingual transcription. Crucially, Whisper transcribes Hindi
# and Marathi in their native Devanagari script (not romanized), which is what
# lets the LLM reply in Devanagari and the TTS then speak it correctly.
#
# The model downloads once from the Hugging Face Hub to the local cache, after
# which it runs offline. It loads on the GPU if available, else CPU.
# ---------------------------------------------------------------------------
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")

_model = None
_lock = threading.Lock()


def _load_model() -> WhisperModel:
    """Load Whisper, preferring the GPU and falling back to CPU on any failure."""
    attempts = []
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            attempts.append(("cuda", "int8_float16"))
    except Exception:
        pass
    attempts.append(("cpu", "int8"))

    last_err = None
    for device, compute_type in attempts:
        try:
            print(f"[STT] Loading Whisper '{WHISPER_MODEL}' on {device} ({compute_type}) ...")
            model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute_type)
            print(f"[STT] Whisper loaded on {device}.")
            return model
        except Exception as e:
            print(f"[STT] Load on {device} failed: {e}")
            last_err = e
    raise RuntimeError(f"Could not load Whisper model: {last_err}")


def get_model() -> WhisperModel:
    """Lazily load and cache the Whisper model (thread-safe)."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = _load_model()
    return _model


def preload_model():
    """Optionally warm up Whisper at startup to avoid first-transcription latency."""
    get_model()


# Languages Milo actually understands. Anything else is almost always a Whisper
# hallucination on non-speech (it loves to guess odd languages on noise).
SUPPORTED_LANGS = {"en", "hi", "mr"}

# Phrases Whisper famously hallucinates on silence / music / background noise.
_HALLUCINATION_PHRASES = (
    "thank you for watching", "thanks for watching", "please subscribe",
    "see you in the next video", "subscribe to", "like and subscribe",
    "thank you.", "thank you", "you're watching", "www.", ".com",
    "amara.org", "transcription by",
)


def _looks_like_hallucination(text: str) -> bool:
    t = text.strip().lower()
    if len(t) < 2:
        return True
    if t in _HALLUCINATION_PHRASES:
        return True
    return any(t == p or (len(t) < 40 and p in t) for p in _HALLUCINATION_PHRASES)


def transcribe(audio_base64: str):
    """
    Transcribe base64-encoded audio (e.g. webm/opus from the browser mic).
    Returns (text, language). Text is in the spoken language's native script.
    Non-speech / hallucinations / unsupported languages return ("", lang).
    """
    if not audio_base64:
        return "", None

    audio_bytes = base64.b64decode(audio_base64)
    model = get_model()

    # vad_filter skips non-speech BEFORE transcribing (kills hallucinations on
    # silence/echo). beam_size=1 (greedy) is fast; temperature=0 avoids random
    # fallbacks that hallucinate.
    segments, info = model.transcribe(
        io.BytesIO(audio_bytes),
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400),
    )
    text = "".join(segment.text for segment in segments).strip()

    lang = info.language
    lang_prob = getattr(info, "language_probability", 1.0)

    # Reject: unsupported language, low confidence, or known hallucinations.
    if lang not in SUPPORTED_LANGS or lang_prob < 0.5 or _looks_like_hallucination(text):
        if text:
            print(f"[STT] rejected (lang={lang} p={lang_prob:.2f}): {text!r}")
        return "", lang

    return text, lang
