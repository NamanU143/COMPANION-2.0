import os
import json
import base64
import requests
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import List

# --- Shared Schemas ---
class EmotionSegment(BaseModel):
    text: str
    emotion: str

class EmotionResponse(BaseModel):
    segments: List[EmotionSegment]

# --- Base Provider ---
class AIProvider(ABC):
    @abstractmethod
    def generate_response(self, user_message: str) -> list[dict]:
        """Generates a list of {"text": "...", "emotion": "..."} segments."""
        pass

    @abstractmethod
    def transcribe_audio(self, audio_base64: str) -> str:
        """Transcribes base64 webm audio into text."""
        pass

    def _get_base_prompt(self, user_message: str) -> str:
        return (
            "You are a helpful desktop AI assistant. Keep your responses brief, conversational, and natural. "
            "IMPORTANT: Do NOT repeat what the user says. Formulate a helpful REPLY to their message. "
            "You must respond ONLY with a valid JSON object containing a 'segments' array. "
            "Each segment must have a 'text' string and an 'emotion' string. "
            "Valid emotions are ONLY: 'happy', 'sad', 'angry', 'surprised', 'thinking', 'neutral'. "
            "DO NOT output any markdown, formatting, code blocks, or explanations. Only output the raw JSON string.\n"
            f"User message: {user_message}"
        )

# --- Google Gemini Provider ---
class GeminiProvider(AIProvider):
    def __init__(self):
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key or api_key == "AIzaSyBnCpnCFb7XV-qAJx6vfIXHNi6eiKYTJSQ":
            api_key = "AIzaSyBnCpnCFb7XV-qAJx6vfIXHNi6eiKYTJSQ" # Default provided by user
        self.api_key = api_key
        
        # Only initialize client if key is present to avoid crashing on import
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None

    def generate_response(self, user_message: str) -> list[dict]:
        if not self.client:
            return [{"text": "Gemini API key is not configured.", "emotion": "sad"}]

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=self._get_base_prompt(user_message),
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': EmotionResponse,
                },
            )
            data = json.loads(response.text)
            return data.get("segments", [{"text": "Error parsing emotion segments.", "emotion": "sad"}])
        except Exception as e:
            print(f"Error calling Gemini: {e}")
            return [{"text": "Sorry, I ran into an error generating a response.", "emotion": "sad"}]

    def transcribe_audio(self, audio_base64: str) -> str:
        if not self.client:
            return "Gemini API key is not configured."

        try:
            from google.genai import types
            audio_bytes = base64.b64decode(audio_base64)
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[
                    "Transcribe this audio exactly. Do not respond to it, just output the spoken text.",
                    types.Part.from_bytes(data=audio_bytes, mime_type='audio/webm')
                ]
            )
            return response.text
        except Exception as e:
            print(f"Error transcribing audio with Gemini: {e}")
            return "I couldn't understand the audio."

# --- Local Ollama Provider ---
class OllamaProvider(AIProvider):
    def __init__(self):
        self.url = "http://localhost:11434/api/chat"
        self.model = "mistral:latest"

    def generate_response(self, user_message: str) -> list[dict]:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": self._get_base_prompt(user_message)
                }
            ],
            "format": "json",
            "stream": False
        }

        try:
            response = requests.post(self.url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            content = data["message"]["content"]
            parsed = json.loads(content)
            return parsed.get("segments", [{"text": "Ollama gave an invalid response format.", "emotion": "sad"}])
        except Exception as e:
            print(f"Error calling Ollama: {e}")
            return [{"text": "Sorry, I ran into an error connecting to local Mistral.", "emotion": "sad"}]

    def transcribe_audio(self, audio_base64: str) -> str:
        # Ollama local (text-only) doesn't natively handle Base64 audio transcription yet in the same API way.
        # Fallback to Gemini for STT if Ollama is selected as the main reasoning engine, OR return a warning.
        print("Note: Local Ollama selected, falling back to Gemini for STT audio decoding.")
        gemini_fallback = GeminiProvider()
        return gemini_fallback.transcribe_audio(audio_base64)

# --- OpenAI Provider ---
class OpenAIProvider(AIProvider):
    def __init__(self):
        import openai
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if self.api_key:
            self.client = openai.OpenAI(api_key=self.api_key)
        else:
            self.client = None

    def generate_response(self, user_message: str) -> list[dict]:
        if not self.client:
            return [{"text": "OpenAI API key is not configured.", "emotion": "sad"}]

        try:
            # We use the pydantic schema to force structured JSON output in modern OpenAI API
            completion = self.client.beta.chat.completions.parse(
                model=os.environ.get("MODEL_NAME", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": "You are a helpful desktop AI assistant."},
                    {"role": "user", "content": self._get_base_prompt(user_message)}
                ],
                response_format=EmotionResponse,
            )
            # OpenAI structured outputs returns parsed model object directly inside message.parsed
            segments = completion.choices[0].message.parsed.segments
            return [{"text": seg.text, "emotion": seg.emotion} for seg in segments]
        except Exception as e:
            print(f"Error calling OpenAI: {e}")
            return [{"text": "Sorry, I ran into an error generating a response with OpenAI.", "emotion": "sad"}]

    def transcribe_audio(self, audio_base64: str) -> str:
        if not self.client:
            return "OpenAI API key is not configured."

        import tempfile
        try:
            # OpenAI requires a file-like object or a temporary file for STT
            audio_bytes = base64.b64decode(audio_base64)
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            with open(tmp_path, "rb") as audio_file:
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1", 
                    file=audio_file,
                    response_format="text"
                )
            
            os.remove(tmp_path)
            return transcript
        except Exception as e:
            print(f"Error transcribing audio with OpenAI: {e}")
            return "I couldn't understand the audio."

# --- Anthropic Provider ---
class AnthropicProvider(AIProvider):
    def __init__(self):
        import anthropic
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)
        else:
            self.client = None

    def generate_response(self, user_message: str) -> list[dict]:
        if not self.client:
            return [{"text": "Anthropic API key is not configured.", "emotion": "sad"}]

        try:
            response = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1024,
                system="You are a helpful desktop AI assistant.",
                messages=[
                    {"role": "user", "content": self._get_base_prompt(user_message)}
                ]
            )
            content = response.content[0].text
            
            # Extract JSON block if it wrapped it in markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            parsed = json.loads(content)
            return parsed.get("segments", [{"text": "Anthropic gave an invalid response format.", "emotion": "sad"}])
        except Exception as e:
            print(f"Error calling Anthropic: {e}")
            return [{"text": "Sorry, I ran into an error generating a response with Anthropic.", "emotion": "sad"}]

    def transcribe_audio(self, audio_base64: str) -> str:
        # Anthropic does not have a native Speech-To-Text API yet.
        print("Note: Anthropic selected, falling back to Gemini for STT audio decoding.")
        gemini_fallback = GeminiProvider()
        return gemini_fallback.transcribe_audio(audio_base64)
