from fastapi import FastAPI, HTTPException, BackgroundTasks
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

# Note: Static mounting is technically no longer needed for audio playback 
# since audio is played directly via sounddevice, but we'll leave it in
# case the user wants to serve other static assets (like images) later.
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

# Mount static files to serve generated audio
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class ChatRequest(BaseModel):
    message: Optional[str] = None
    audio_base64: Optional[str] = None

@app.post("/chat")
async def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks):
    try:
        if request.audio_base64:
            user_message = transcribe_audio(request.audio_base64)
            print(f"Transcribed User Audio: {user_message}")
        else:
            user_message = request.message or ""
        
        # 1. Get AI Response
        ai_segments = generate_ai_response(user_message)
        
        # Combine all text segments into one string for TTS
        full_text = " ".join([seg["text"] for seg in ai_segments])
        print(f"AI Response: {full_text}")
        
        # 2. Trigger audio playback in the background so the UI doesn't hang
        #    We pass the 'full_text' to the background task which will stream via `sounddevice`.
        background_tasks.add_task(generate_audio, full_text, "")
        
        # 3. Return JSON response immediately
        return {
            "text": full_text,
            "segments": ai_segments,
            "audio_url": None # No longer returning an audio URL as playback is instantaneous on the host
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
