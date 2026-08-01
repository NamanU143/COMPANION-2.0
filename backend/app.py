from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import time
import base64
import asyncio
from dotenv import load_dotenv

from ai_service import generate_ai_response, generate_ai_response_stream, transcribe_audio
from ai_providers import _might_need_tool
from tts_service import generate_audio, synthesize_pcm, split_sentences, list_voice_styles
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


@app.on_event("startup")
async def _warmup():
    """
    Warm up the slow-to-initialize pieces in the background so the first real
    user turn is fast: load the TTS voices + Whisper into memory, and open the
    LLM connection (its first call has a cold TLS/connection penalty).
    """
    async def warm():
        try:
            from tts_service import preload_models
            from stt_service import preload_model
            from ai_service import generate_ai_response_stream

            await asyncio.to_thread(preload_models)  # MMS voices (EN/HI/MR)
            await asyncio.to_thread(preload_model)    # Whisper STT

            def ping_llm():
                for _ in generate_ai_response_stream("hi"):
                    break  # first sentence is enough to open the connection

            await asyncio.to_thread(ping_llm)
            print("[WARMUP] TTS + STT models loaded and LLM connection ready.")
        except Exception as e:
            print(f"[WARMUP] error (non-fatal): {e}")

    asyncio.create_task(warm())


@app.on_event("startup")
async def _activity_logger():
    """Background loop: record the active window title whenever it changes."""
    import activity_logger

    async def loop():
        last = ""
        while True:
            try:
                last = await asyncio.to_thread(activity_logger.record_once, last)
            except Exception as e:
                print(f"[activity] loop error: {e}")
            await asyncio.sleep(20)

    asyncio.create_task(loop())


@app.get("/voices")
async def voices():
    """List selectable voice styles for the UI dropdown."""
    return {"voices": list_voice_styles()}


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


# ---------------------------------------------------------------------------
# Real-time conversational WebSocket
# ---------------------------------------------------------------------------
# Protocol (JSON frames):
#   Client -> Server:
#     {"type": "audio", "turn": <int>, "data": "<base64 webm>"}  -> a finished user turn
#     {"type": "interrupt", "turn": <int>}                        -> user barged in; cancel
#   Server -> Client:
#     {"type": "transcript", "turn": n, "text": ...}   -> what the user said
#     {"type": "segment",    "turn": n, "text", "emotion"}  -> per emotion segment
#     {"type": "audio",      "turn": n, "emotion", "sample_rate", "data": <base64 pcm16>}
#     {"type": "turn_end",   "turn": n}                -> Milo finished this turn
#     {"type": "interrupted","turn": n}                -> turn was cancelled
#     {"type": "error",      "turn": n, "message": ...}
# ---------------------------------------------------------------------------
# Wake-word gating for VOICE turns. After the wake word, a short follow-up window
# lets the conversation continue without repeating it. Text input always bypasses this.
WAKE_ENABLED = os.environ.get("MILO_WAKE_WORD", "1") != "0"
WAKE_WORDS = ("milo", "mylo", "maylo", "meelo", "mailo")
FOLLOWUP_WINDOW_S = 25.0


def _strip_wake_word(text: str) -> str:
    """Remove a leading 'hey milo' / 'milo' address from the utterance."""
    import re
    return re.sub(r"^\s*(hey|hi|hello|ok|okay)?\s*(milo|mylo|maylo|meelo|mailo)[\s,\.!]*",
                  "", text, count=1, flags=re.IGNORECASE).strip()


@app.websocket("/ws")
async def conversational_ws(ws: WebSocket):
    await ws.accept()
    print("[WS] Client connected.")
    current_task: Optional[asyncio.Task] = None
    last_interaction = [0.0]  # monotonic time of last accepted turn (mutable for closure)

    async def handle_turn(turn: int, audio_b64: str = None, text: str = None, style: str = "milo"):
        try:
            t0 = time.monotonic()
            # 1. Get the user's text — either transcribe audio (blocking -> thread)
            #    or use text typed into the composer.
            if text is not None:
                user_text = text.strip()
            else:
                user_text = await asyncio.to_thread(transcribe_audio, audio_b64)
                user_text = (user_text or "").strip()
                print(f"[timing] turn {turn}: STT {time.monotonic() - t0:.2f}s")

                # Wake-word gate (voice only): require "Milo" unless we're mid-conversation.
                if WAKE_ENABLED and user_text:
                    lc = user_text.lower()
                    has_wake = any(w in lc for w in WAKE_WORDS)
                    recent = (time.monotonic() - last_interaction[0]) < FOLLOWUP_WINDOW_S
                    if not has_wake and not recent:
                        await ws.send_json({"type": "ignored", "turn": turn, "text": user_text})
                        await ws.send_json({"type": "turn_end", "turn": turn})
                        return
                    if has_wake:
                        user_text = _strip_wake_word(user_text) or user_text

            await ws.send_json({"type": "transcript", "turn": turn, "text": user_text})

            # Gate: ignore empty / non-speech turns (background noise, silence)
            if not user_text:
                await ws.send_json({"type": "turn_end", "turn": turn})
                return

            last_interaction[0] = time.monotonic()

            # 2. Stream Milo's reply sentence-by-sentence. Each sentence is
            #    synthesized and sent as soon as the LLM produces it, so playback
            #    starts on sentence 1 instead of after the whole reply (low latency).
            #    We pull the (blocking) generator through a thread-backed queue.
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()
            _SENTINEL = object()

            def produce():
                try:
                    for seg in generate_ai_response_stream(user_text):
                        loop.call_soon_threadsafe(queue.put_nowait, seg)
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

            producer = asyncio.create_task(asyncio.to_thread(produce))
            got_any = False
            first_audio = False
            try:
                while True:
                    seg = await queue.get()
                    if seg is _SENTINEL:
                        break
                    got_any = True
                    emotion = seg.get("emotion", "neutral")
                    seg_text = seg.get("text", "")
                    await ws.send_json({"type": "segment", "turn": turn, "text": seg_text, "emotion": emotion})
                    pcm, sr = await asyncio.to_thread(synthesize_pcm, seg_text, None, emotion, style)
                    if pcm:
                        if not first_audio:
                            first_audio = True
                            print(f"[timing] turn {turn}: first audio {time.monotonic() - t0:.2f}s "
                                  f"(tool_path={_might_need_tool(user_text)})")
                        await ws.send_json({
                            "type": "audio",
                            "turn": turn,
                            "emotion": emotion,
                            "sample_rate": sr,
                            "data": base64.b64encode(pcm).decode("ascii"),
                        })
            finally:
                producer.cancel()

            if not got_any:
                await ws.send_json({"type": "turn_end", "turn": turn})
                return

            last_interaction[0] = time.monotonic()  # keep the follow-up window open
            print(f"[timing] turn {turn}: total {time.monotonic() - t0:.2f}s")
            await ws.send_json({"type": "turn_end", "turn": turn})
        except asyncio.CancelledError:
            print(f"[WS] Turn {turn} interrupted.")
            try:
                await ws.send_json({"type": "interrupted", "turn": turn})
            except Exception:
                pass
            raise
        except Exception as e:
            print(f"[WS] Turn {turn} error: {e}")
            try:
                await ws.send_json({"type": "error", "turn": turn, "message": str(e)})
            except Exception:
                pass

    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            turn = int(msg.get("turn", 0))

            if mtype == "audio":
                # A new user turn — cancel anything still running, then start fresh.
                if current_task and not current_task.done():
                    current_task.cancel()
                current_task = asyncio.create_task(
                    handle_turn(turn, audio_b64=msg.get("data", ""), style=msg.get("style", "milo")))
            elif mtype == "text":
                if current_task and not current_task.done():
                    current_task.cancel()
                current_task = asyncio.create_task(
                    handle_turn(turn, text=msg.get("text", ""), style=msg.get("style", "milo")))
            elif mtype == "interrupt":
                # User barged in — stop Milo immediately.
                if current_task and not current_task.done():
                    current_task.cancel()
    except WebSocketDisconnect:
        print("[WS] Client disconnected.")
        if current_task and not current_task.done():
            current_task.cancel()
