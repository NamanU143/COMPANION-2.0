import os
from ai_providers import GeminiProvider, OllamaProvider, OpenAIProvider, AnthropicProvider

# Cache provider instances so we don't rebuild the client (and reopen the network
# connection) on every turn — that setup cost was adding seconds of latency.
_provider_cache = {}

def get_provider():
    """Returns the correct AIProvider instance based on environment variables (cached)."""
    provider_name = os.environ.get("LLM_PROVIDER", "gemini").lower()

    if provider_name in _provider_cache:
        return _provider_cache[provider_name]

    if provider_name == "openai":
        print(f"Using Hosted OpenAI Model: {os.environ.get('MODEL_NAME', 'gpt-4o-mini')}")
        provider = OpenAIProvider()
    elif provider_name == "anthropic":
        print("Using Hosted Anthropic API: claude-3-haiku")
        provider = AnthropicProvider()
    elif provider_name == "ollama":
        print("Using Local Ollama Model: mistral")
        provider = OllamaProvider()
    else:
        print("Using Hosted Gemini API: gemini-flash-lite-latest")
        provider = GeminiProvider()

    _provider_cache[provider_name] = provider
    return provider

def generate_ai_response(user_message: str) -> list[dict]:
    """
    Routes the AI generation to the configured provider instance.
    """
    provider = get_provider()
    return provider.generate_response(user_message)

def generate_ai_response_stream(user_message: str):
    """
    Streaming generation: yields {"text", "emotion"} segments as they are produced,
    so downstream TTS can start on the first sentence (low latency).
    """
    provider = get_provider()
    return provider.generate_response_stream(user_message)

def transcribe_audio(audio_base64: str) -> str:
    """
    Speech-to-Text via the self-hosted Whisper model (high-quality, multilingual,
    outputs native script). This replaces the old per-provider transcription so
    Hindi/Marathi come back in Devanagari instead of romanized text.
    """
    from stt_service import transcribe
    text, language = transcribe(audio_base64)
    print(f"[STT] ({language}) {text}")
    return text
