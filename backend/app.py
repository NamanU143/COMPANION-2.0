from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
from dotenv import load_dotenv

from ai_service import generate_ai_response, transcribe_audio
from tts_service import generate_audio
from typing import Optional

load_dotenv()

app = FastAPI()

# Allow CORS for Electron frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Ensure static directory exists
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

# Mount static files to serve generated audio
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class ChatRequest(BaseModel):
    message: Optional[str] = None
    audio_base64: Optional[str] = None

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        if request.audio_base64:
            user_message = transcribe_audio(request.audio_base64)
            print(f"Transcribed User Audio: {user_message}")
        else:
            user_message = request.message or ""
        
        # 1. Get AI Response (now a list of segment dicts)
        ai_segments = generate_ai_response(user_message)
        
        # Combine all text segments into one string for TTS
        full_text = " ".join([seg["text"] for seg in ai_segments])
        print(f"AI Response: {full_text}")
        
        # 2. Convert to Speech
        audio_filename = "response.wav"
        audio_filepath = os.path.join(STATIC_DIR, audio_filename)
        
        await generate_audio(full_text, audio_filepath)
        
        # 3. Return JSON response containing audio mapping + segments
        return {
            "text": full_text, # Keep for backwards compatibility/logging
            "segments": ai_segments,
            "audio_url": f"http://127.0.0.1:8000/static/{audio_filename}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
