import os
from ai_providers import GeminiProvider, OllamaProvider, OpenAIProvider, AnthropicProvider

def get_provider():
    """Returns the correct AIProvider instance based on environment variables."""
    provider_name = os.environ.get("LLM_PROVIDER", "gemini").lower()
    
    if provider_name == "openai":
        print(f"Using Hosted OpenAI Model: {os.environ.get('MODEL_NAME', 'gpt-4o-mini')}")
        return OpenAIProvider()
    elif provider_name == "anthropic":
        print("Using Hosted Anthropic API: claude-3-haiku")
        return AnthropicProvider()
    elif provider_name == "ollama":
        print("Using Local Ollama Model: mistral")
        return OllamaProvider()
    else:
        print("Using Hosted Gemini API: gemini-2.5-flash")
        return GeminiProvider()

def generate_ai_response(user_message: str) -> list[dict]:
    """
    Routes the AI generation to the configured provider instance.
    """
    provider = get_provider()
    return provider.generate_response(user_message)

def transcribe_audio(audio_base64: str) -> str:
    """
    Routes Speech-to-Text decoding to the configured provider instance.
    """
    provider = get_provider()
    return provider.transcribe_audio(audio_base64)
