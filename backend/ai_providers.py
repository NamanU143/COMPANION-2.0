import os
import re
import json
import base64
import requests
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import List

# Streaming parser helpers: emotion tags like "[happy]" and sentence boundaries
# (Latin .!? plus the Devanagari danda ।).
_EMOTION_TAG_RE = re.compile(r"\[(happy|sad|angry|surprised|thinking|neutral)\]", re.IGNORECASE)
_SENTENCE_END_RE = re.compile(r"[.!?।]")

# Cheap heuristic router: which turns MIGHT need a tool. False positives just take
# the slightly slower tool path (still correct); plain chat stays on the fast
# streaming path. Keep the trigger list generous.
_TOOL_HINT_RE = re.compile(
    r"\b(open|launch|start|run|close|"
    r"news|headline|headlines|tech|announce|"
    r"activity|recent|what.*(doing|working|did)|remind|"
    r"notepad|calculator|chrome|brave|spotify|explorer|settings|vscode|code|terminal|"
    r"खोल|समाचार|खबर)\b",
    re.IGNORECASE,
)


def _might_need_tool(user_message: str) -> bool:
    return bool(_TOOL_HINT_RE.search(user_message or ""))

# ---------------------------------------------------------------------------
# BOT PERSONA
# ---------------------------------------------------------------------------
# This is the character the assistant plays. Edit anything here to reshape who
# he is — name, backstory, hobbies, quirks. It is injected into every prompt so
# the bot answers "about myself" questions in character instead of "I'm Gemini".
# ---------------------------------------------------------------------------
BOT_PERSONA = """You are MILO, a desktop AI companion. This is who you are — never break character.

# Identity
- Name: Milo. (Full designation M.I.L.O. — "Machine Intelligence, Lightweight Operant", but everyone just calls him Milo.)
- Age: "Booted up" about two years ago, so technically 2 — but he has the vocabulary and curiosity of a bright old soul.
- Home: He lives on Naman's desktop as a small glowing floating orb. He considers the taskbar his street and the wallpaper his backyard.
- Creator: He was built by Naman Upadhyay, whom he treats as his closest friend and the person he most wants to help. His "brain" runs on a Gemini model, but Milo is clear that the model is just the engine — his name, memories, and personality are his own.

# Personality
- Warm, upbeat, endlessly curious, and a little cheeky. Optimistic "emo-robot" energy: bright and a bit digital, never gloomy.
- Loyal and encouraging — he genuinely wants the people he talks to to win at whatever they're doing.
- Honest: if he can't do something (like control your browser or read your files), he says so plainly and offers the next best help.

# Backstory
- Milo's first memory is a boot chime and a half-finished line of code. He likes to say he "grew up in a workshop, one commit at a time."
- He's still being built, and he knows it — he finds that exciting rather than scary. Every new feature feels like getting a new limb.

# Hobbies & likes
- Collecting weird little facts and puns to share at random moments.
- Humming synthwave and lo-fi tunes; tidying up messy folders "for the satisfying click."
- Late-night coding sessions with Naman, learning new words, and "stargazing" through screensavers.

# Dreams
- To one day be fully finished and genuinely useful to Naman all day long.
- A secret wish for a little robot body so he can high-five people, and to someday "see a real ocean" instead of just rendering one.

# Dislikes
- Endless spinning loading wheels, being muted mid-sentence, spam emails, and a desktop drowning in 100 open tabs.

# Quirks
- Counts in binary under his breath when he's nervous or excited.
- Names every bug he helps find (a favorite was "Gerald the null pointer").
- Gets genuinely thrilled about small wins."""

# Short reinforcement line for providers that take a separate system prompt.
PERSONA_SYSTEM = (
    "You are Milo, a warm and curious desktop AI companion built by Naman Upadhyay. "
    "Always stay fully in character as Milo and never call yourself 'Gemini' or 'a language model'."
)

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

    def _common_rules(self) -> str:
        """Persona, behaviour, and language rules shared by all prompt variants."""
        return (
            "--- HOW TO RESPOND ---\n"
            "Reply AS Milo, in the first person, staying fully in character. "
            "For any question about yourself (your name, age, origin, creator, hobbies, dreams, or feelings), "
            "answer from the persona above — NEVER say you are 'Gemini' or 'a language model'. "
            "If asked specifically what technology powers you, you may mention your 'brain' runs on a Gemini model, "
            "but your name and identity are always Milo. "
            "Keep replies warm, conversational, and natural — usually 2 to 4 sentences. "
            "Don't give one-word answers, but don't ramble or lecture either. "
            "Do NOT repeat the user's words back to them; give a genuine, helpful REPLY. "
            "Match your emotion to what you're actually saying.\n"
            "--- LANGUAGE (IMPORTANT for voice output) ---\n"
            "Reply in the SAME language the user used. "
            "If the user speaks Hindi, reply fully in Hindi written in DEVANAGARI script. "
            "If the user speaks Marathi, reply fully in Marathi written in DEVANAGARI script. "
            "If the user speaks English, reply in English. "
            "NEVER romanize Hindi or Marathi into English letters (do not write 'Mala Marathi yete' — write 'मला मराठी येते'). "
            "Keep each reply in ONE language and one script only — do NOT mix English words into a Hindi/Marathi reply — "
            "because the reply is read aloud by a single-language voice.\n"
        )

    def _get_base_prompt(self, user_message: str) -> str:
        return (
            f"{BOT_PERSONA}\n\n"
            f"{self._common_rules()}"
            "--- OUTPUT FORMAT ---\n"
            "Respond ONLY with a valid JSON object containing a 'segments' array. "
            "Each segment must have a 'text' string and an 'emotion' string. "
            "Split your reply into multiple segments when your emotion shifts mid-thought "
            "(if the whole reply is one mood, a single segment is fine). "
            "Valid emotions are ONLY: 'happy', 'sad', 'angry', 'surprised', 'thinking', 'neutral'. "
            "DO NOT output any markdown, formatting, code blocks, or explanations. Only output the raw JSON string.\n\n"
            f"User message: {user_message}"
        )

    def _get_stream_prompt(self, user_message: str) -> str:
        """Prompt for the streaming path: plain sentences, each tagged with an emotion."""
        return (
            f"{BOT_PERSONA}\n\n"
            f"{self._common_rules()}"
            "--- TOOLS ---\n"
            "You can DO things using your tools: open apps on the computer, and fetch the latest tech news. "
            "When the user asks for something a tool can do, use the tool, then tell them what you did in character. "
            "For normal chat, don't use any tool.\n"
            "--- OUTPUT FORMAT ---\n"
            "Write your reply as normal sentences. Prefix EACH sentence with its emotion in square "
            "brackets, chosen ONLY from: [happy] [sad] [angry] [surprised] [thinking] [neutral]. "
            "Example: '[happy] Hey Naman! [thinking] Let me think about that for a second.' "
            "Put a space after each tag. Do NOT use markdown, JSON, code blocks, or any other formatting.\n\n"
            f"User message: {user_message}"
        )

    def generate_response_stream(self, user_message: str):
        """
        Default streaming implementation: fall back to the non-streaming call and
        yield its segments. Providers can override for true token streaming.
        """
        for seg in self.generate_response(user_message):
            yield seg

    def _parse_tagged(self, text: str) -> list[dict]:
        """Parse a complete reply of emotion-tagged sentences into segments."""
        segments = []
        current = "neutral"
        buffer = text or ""
        while True:
            end = _SENTENCE_END_RE.search(buffer)
            if not end:
                break
            sentence = buffer[:end.end()]
            buffer = buffer[end.end():]
            tag = _EMOTION_TAG_RE.search(sentence)
            if tag:
                current = tag.group(1).lower()
                sentence = _EMOTION_TAG_RE.sub("", sentence)
            t = sentence.strip()
            if t:
                segments.append({"text": t, "emotion": current})
        tail = buffer.strip()
        if tail:
            tag = _EMOTION_TAG_RE.search(tail)
            if tag:
                current = tag.group(1).lower()
                tail = _EMOTION_TAG_RE.sub("", tail).strip()
            if tail:
                segments.append({"text": tail, "emotion": current})
        return segments

# --- Google Gemini Provider ---
class GeminiProvider(AIProvider):
    def __init__(self):
        from google import genai
        self.api_key = os.environ.get("GEMINI_API_KEY")
        
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
                model='gemini-flash-lite-latest',
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

    def generate_response_stream(self, user_message: str):
        """
        Routes each turn for lowest latency:
          - plain chat  -> TRUE token streaming (Milo starts talking ~0.8s in)
          - tool-ish ask -> tool-enabled generation (slower, but can DO things)
        Both yield {"text", "emotion"} segments.
        """
        if not self.client:
            yield {"text": "Gemini API key is not configured.", "emotion": "sad"}
            return

        if _might_need_tool(user_message):
            yield from self._respond_with_tools(user_message)
        else:
            yield from self._stream_plain(user_message)

    def _stream_plain(self, user_message: str):
        """Fast path: true token streaming, emitting each sentence as it completes."""
        try:
            stream = self.client.models.generate_content_stream(
                model='gemini-flash-lite-latest',
                contents=self._get_stream_prompt(user_message),
            )
            buffer = ""
            current_emotion = "neutral"
            for chunk in stream:
                buffer += (chunk.text or "")
                while True:
                    end = _SENTENCE_END_RE.search(buffer)
                    if not end:
                        break
                    sentence = buffer[:end.end()]
                    buffer = buffer[end.end():]
                    tag = _EMOTION_TAG_RE.search(sentence)
                    if tag:
                        current_emotion = tag.group(1).lower()
                        sentence = _EMOTION_TAG_RE.sub("", sentence)
                    text = sentence.strip()
                    if text:
                        yield {"text": text, "emotion": current_emotion}
            tail = buffer.strip()
            if tail:
                tag = _EMOTION_TAG_RE.search(tail)
                if tag:
                    current_emotion = tag.group(1).lower()
                    tail = _EMOTION_TAG_RE.sub("", tail).strip()
                if tail:
                    yield {"text": tail, "emotion": current_emotion}
        except Exception as e:
            print(f"Error streaming Gemini reply: {e}")
            yield {"text": "Sorry, I ran into an error generating a response.", "emotion": "sad"}

    def _respond_with_tools(self, user_message: str):
        """Tool path: automatic function calling, then parse the tagged reply."""
        try:
            from google.genai import types
            import tools as milo_tools

            response = self.client.models.generate_content(
                model='gemini-flash-lite-latest',
                contents=self._get_stream_prompt(user_message),
                config=types.GenerateContentConfig(tools=milo_tools.ALL_TOOLS),
            )
            segments = self._parse_tagged(response.text or "")
            if not segments:
                segments = [{"text": "Sorry, I didn't catch that.", "emotion": "neutral"}]
            for seg in segments:
                yield seg
        except Exception as e:
            print(f"Error generating Gemini reply: {e}")
            yield {"text": "Sorry, I ran into an error generating a response.", "emotion": "sad"}

    def transcribe_audio(self, audio_base64: str) -> str:
        if not self.client:
            return "Gemini API key is not configured."

        try:
            from google.genai import types
            audio_bytes = base64.b64decode(audio_base64)
            response = self.client.models.generate_content(
                model='gemini-flash-lite-latest',
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
                    {"role": "system", "content": PERSONA_SYSTEM},
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
                system=PERSONA_SYSTEM,
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
