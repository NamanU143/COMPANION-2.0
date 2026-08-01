# Milo — Progress Report

_Desktop AI companion. This report summarizes the work done to bring Milo from a
button-click prototype to a real-time, multilingual, conversational agent._

---

## 1. What Milo is now

A floating desktop companion ("Milo") that you talk to by voice (or text). He:
- **Hears** you in English, Hindi, or Marathi (native-script transcription)
- **Thinks** with a persona-driven brain and replies in the language you spoke
- **Speaks** back with a natural, self-hosted voice per language
- **Feels real-time**: streams his reply, starts talking ~1s in, and you can **interrupt** him mid-sentence

---

## 2. The model stack ("brain / ears / voice")

| Role | Model | Hosting | Notes |
|------|-------|---------|-------|
| 🧠 Brain (reasoning) | **Gemini `gemini-flash-lite-latest`** | Cloud (Google) | Chosen for free-tier quota; swappable via `LLM_PROVIDER` |
| 👂 Ears (STT) | **Whisper `large-v3`** (faster-whisper) | Local GPU (RTX 2050, int8_float16) | Native Devanagari for HI/MR |
| 🗣️ Voice (TTS) | **Meta MMS-TTS** (eng/hin/mar VITS) | Local CPU | Auto-selected by reply language |

Only the brain is cloud-based; ears and voice are fully self-hosted/offline.

---

## 3. Architecture — the real-time loop

```
┌─────────── Electron (renderer.js) ───────────┐        ┌────────── FastAPI (app.py) ──────────┐
│ mic (echoCancellation) → energy VAD          │        │  /ws WebSocket                        │
│   • turn end (550ms silence) → webm          │──ws──▶ │  audio → Whisper → text              │
│   • barge-in: speech over Milo → interrupt   │        │  text  → Gemini (STREAMED, tagged)   │
│ Web Audio playback (queued PCM) + lip-sync   │◀─ws──  │  per sentence → MMS-TTS → PCM chunk   │
│ face: eyes/brows/mouth, emotion, aura, caps  │        │  interrupt → cancel turn             │
└──────────────────────────────────────────────┘        └──────────────────────────────────────┘
```

**Key design decisions**
- **WebSocket** (not one-shot HTTP): needed for barge-in signaling + streaming audio.
- **Playback moved to the browser** (Web Audio): so `echoCancellation` cancels Milo's
  own voice from the mic → the mic can stay open while he speaks → **barge-in works**,
  and the frontend knows exactly when audio ends (no more `msPerChar` guessing).
- **Sentence-streamed TTS**: Gemini streams token-by-token with inline emotion tags
  (`[happy] ...`); each finished sentence is synthesized and sent immediately, so
  playback starts on sentence 1.
- **Turn IDs**: audio from an interrupted turn is discarded by the client.

---

## 4. Latency (human-like target)

| Stage | Cost |
|-------|------|
| End-of-turn silence | ~0.55s (was 1.0s) |
| Whisper STT (GPU, short clip) | ~0.3–0.6s |
| Gemini time-to-first-sentence (warm) | ~0.8–1.0s |
| MMS TTS (first sentence, CPU) | ~0.3–0.5s |
| **≈ user stops → Milo starts** | **~2.0–2.5s** |

**Optimizations applied**
- **Provider caching** — the Gemini client was being rebuilt (new connection) every
  turn, adding seconds. Now cached as a singleton.
- **Startup warm-up** — TTS voices + Whisper + the LLM connection are pre-loaded on
  server boot, so the first real turn isn't cold (cold first call was ~2.7s).
- **Streaming** — Milo starts speaking on the first sentence, not the whole reply.

---

## 5. Persona

Milo has a full character in `BOT_PERSONA` (`ai_providers.py`) — name, backstory,
creator (Naman Upadhyay), hobbies, dreams, quirks. He answers "about-me" questions in
character and never says "I'm Gemini". Language rule: reply in the user's language,
Devanagari for HI/MR, never romanized, one language per reply (for clean TTS).

---

## 6. UI

Redesigned from a 120px cube into a **340×460 glass panel**:
- Circular avatar with a **state aura** (cyan=listening, purple=thinking, green=speaking)
- Expressive face: eyes + pupils, eyebrows, mouth
- **Lip-sync**: mouth opening driven by live playback amplitude
- **Emotion**: happy / sad / angry / surprised / thinking / neutral shapes
- **Live captions** (You / Milo), status pill, **text composer**, mute / minimize / close

---

## 7. Files changed this session

**Backend**
- `.env` — working Gemini key
- `ai_providers.py` — persona, language rules, `gemini-flash-lite-latest`, streaming generator with emotion tags
- `ai_service.py` — provider caching, `generate_ai_response_stream`, Whisper transcription
- `stt_service.py` *(new)* — Whisper large-v3
- `tts_service.py` — MMS-TTS multilingual, `synthesize_pcm` / `split_sentences`
- `app.py` — `/ws` WebSocket (audio/text/interrupt, streaming), startup warm-up
- `requirements.txt` — updated (torch, transformers, faster-whisper, langdetect; dropped piper/edge)

**Frontend**
- `main.js` — larger window, close handler, DevTools gated behind `MILO_DEVTOOLS`
- `index.html` — new panel structure
- `style.css` — full redesign
- `renderer.js` — real-time WS loop, VAD, barge-in, Web Audio playback, lip-sync, captions, controls

---

## 8. Known limitations / caveats

1. **VAD is energy-based**, not Silero — can trip on loud background noise or miss very
   soft speech. Thresholds are tunable at the top of the VAD section in `renderer.js`.
   Silero VAD is the robustness upgrade.
2. **Barge-in depends on browser echo cancellation.** If Milo interrupts himself, raise
   `BARGEIN_THRESHOLD` (or use headphones). Server-side AEC is a future option.
3. **Brain is cloud** (Gemini) and **free-tier limited** — heavy testing can hit quota.
   Fully-offline would mean a local LLM (Ollama).
4. **Marathi STT** occasionally uses slightly Hindi-ish spellings (the languages are
   close), but it's reliably Devanagari, which is what makes the voice work.
5. **One language per reply** — code-switching (Hinglish) in a single reply isn't spoken
   cleanly yet (single-language voice per utterance).

---

## 9. Tools (Milo can now DO things)

Milo has a **tool-calling foundation** (`backend/tools.py`) — Gemini decides when to
call a tool via automatic function calling, then replies in character. Add new tools by
appending to `ALL_TOOLS`.

| Tool | What it does | Status |
|------|--------------|--------|
| `open_application(app_name)` | Launches a Windows app (notepad, chrome, spotify, …) | ✅ working |
| `get_tech_news(count)` | Latest tech headlines (Hacker News) | ✅ working |
| `get_my_recent_activity(limit)` | Reads the on-device activity log (recent windows/apps) | ✅ working |

**Activity logger** (`backend/activity_logger.py`): a background loop records the active
window title whenever it changes, to `activity_log.jsonl` (local-only, gitignored).

**Wake word**: voice turns require "Milo"/"Hey Milo" (env `MILO_WAKE_WORD=0` to disable),
with a 25s follow-up window so a conversation flows without repeating it. Text input
always bypasses the wake word.

## 10. Feature roadmap

**Done this session** ✅ Windows control · Tech news · Activity-log awareness · Wake word

**Next**
- **Gmail** — read/summarize inbox, draft replies (send behind confirmation).
  _Blocked on your action:_ needs a Google Cloud OAuth client + one-time consent.
- **More Windows tools** — type/click/screenshot, search files, control media/volume.
- **Proactivity** — reminders, scheduled check-ins, Milo speaking first.
- **Memory** — remember facts about you across sessions.

**Polish**
- Silero VAD + streaming STT (partial transcripts), server-side AEC
- Local LLM option (Ollama) for a fully-offline brain

---

## 11. How to run

```bash
# Backend (from backend/)
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload

# Frontend (from desktop-app/)
npm start
```
Set `MILO_DEVTOOLS=1` before `npm start` to open Electron DevTools.
