import os
import json
import wave
import numpy as np
import sounddevice as sd
from piper import PiperVoice
from scipy import signal

# Define model paths
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "en_US-danny-low.onnx")
CONFIG_PATH = os.path.join(MODEL_DIR, "en_US-danny-low.onnx.json")

# In-memory global instance to ensure sub-200ms latency.
# We initialize it as None and load it when needed (or on server startup).
_piper_voice = None


def get_piper_voice() -> PiperVoice:
    """Loads the Piper ONNX model into memory globally as a singleton."""
    global _piper_voice
    if _piper_voice is None:
        if not os.path.exists(MODEL_PATH) or not os.path.exists(CONFIG_PATH):
            raise FileNotFoundError(
                f"Piper model not found at {MODEL_PATH}. Did you download it?"
            )
        print(f"Loading Piper ONNX model from {MODEL_PATH}...")
        _piper_voice = PiperVoice.load(MODEL_PATH, config_path=CONFIG_PATH)
        print("Piper model loaded into memory.")
    return _piper_voice


def apply_robotic_texture(audio_array: np.ndarray, sample_rate: int) -> np.ndarray:
    """
    Applies a lightweight audio manipulation to give the voice an "EMO bot" texture.
    We'll do a slight pitch/speed increase by resampling, which makes it sound smaller,
    more energetic, and slightly digital/robotic.
    """
    # Speed up / Pitch up factor. 1.15x is usually a good sweet spot for a cute/robotic effect
    # on a voice like danny-low without it becoming completely unintelligible chipmunk.
    speed_factor = 1.15

    # Calculate new length
    new_length = int(len(audio_array) / speed_factor)

    # Resample the audio array (this fundamentally shifts pitch and speed together,
    # which sounds like a fast-talking little robot).
    resampled_audio = signal.resample(audio_array, new_length)

    # Optional: Add a very tiny bit of static or quantization noise for extra "robot" flavor
    # noise = np.random.normal(0, 0.005, resampled_audio.shape)
    # resampled_audio = resampled_audio + noise

    # Ensure it stays within int16 bounds
    return np.clip(resampled_audio, -32768, 32767).astype(np.int16)


def speak(text: str):
    """
    Synthesizes speech and plays it directly via sounddevice, bypassing the disk entirely.
    """
    voice = get_piper_voice()

    # In a "low" quality Piper model, the sample rate is usually 22050
    sample_rate = voice.config.sample_rate

    print(f"Synthesizing audio stream for: {text[:50]}...")

    # synthesize_stream_raw returns an iterator of raw int16 PCM bytes
    audio_stream = voice.synthesize_stream_raw(text)

    # Collect all chunks to apply the robotic numpy effect over the whole phrase
    # (Doing it chunk-by-chunk with resampling can cause clicking artifacts at boundaries)
    raw_bytes = b"".join(chunk for chunk in audio_stream)

    # Convert bytes to numpy array
    audio_array = np.frombuffer(raw_bytes, dtype=np.int16)

    # Apply "EMO Bot" Pitch/Speed Shift Texture
    processed_array = apply_robotic_texture(audio_array, sample_rate)

    # Play directly to the default audio output device using sounddevice
    # Note: Because we resampled the data but tell sounddevice to play it at the
    # ORIGINAL sample_rate, it plays faster and higher-pitched!
    print("Playing audio...")
    sd.play(processed_array, samplerate=sample_rate)
    sd.wait()  # Wait until the audio is finished playing
    print("Playback finished.")


# Optional: async wrapper if we need it for FastAPI compatibility later
async def generate_audio(text: str, output_filepath: str):
    """
    Legacy compatible function just in case app.py still calls this.
    Instead of writing to output_filepath, it just uses direct playback.
    We ignore the output_filepath!
    """
    speak(text)


# To do :
# 1. Implement proper error handling and logging as needed for production use.
# 2. Update the tts service api with the pretrained model and ruunning it in memory for sub-200ms latency.
# 3. Ensure that the model files are included in the deployment package and that the paths are correct.
# 4. Update the notebook for new RND related to finetuining the model for the emo bot voice and the new audio processing pipeline.
# 5. Test the new TTS service with various inputs to ensure it meets the latency and quality requirements.
