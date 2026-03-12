# Desktop AI Companion

The **Desktop AI Companion** is a voice-enabled, real-time desktop application designed to act as a personal AI assistant. It bridges the gap between a sleek desktop interface and powerful backend AI processing, supporting both cloud-based and fully local text and voice capabilities.

## 🌟 Key Features & Architecture

### 1. Multi-Provider AI Brain
The backend is built with **FastAPI** and is highly modular. It allows you to seamlessly switch between different AI models depending on your needs (speed, privacy, or reasoning power):
- **Hosted / Cloud:** OpenAI (GPT-4o), Anthropic (Claude 3 Haiku), and Google Gemini.
- **Fully Local / Offline:** Ollama (running Mistral), ensures ultimate privacy and allows the app to run on your local hardware (optimized for low VRAM GPUs).

### 2. Voice-First Interaction
Designed for natural conversation instead of just typing:
- **Speech-to-Text (STT):** Accepts audio input (via hold-to-record mic) and transcribes your voice into text.
- **Text-to-Speech (TTS):** Generates spoken audio from the AI's text responses. The backend dynamically creates `.wav` files and serves them to the frontend so the AI can "talk back".

### 3. Native Desktop Experience
The frontend is packaged using **Electron**, making it feel like a native desktop app rather than a browser tab. The API uses CORS middleware to communicate smoothly with the native Electron window.

### 4. Real-time REST API
The core engine relies on a robust API backend:
- Transcribes user audio if necessary.
- Routes prompts to your chosen AI provider.
- Converts AI generated responses into speech.
- Returns text segments and the playable audio URL seamlessly to the user interface.

## 🚀 Getting Started

To run the project, you need to start both the Python backend and the Electron frontend.

### 1. Start the Backend

The backend engine runs on Python, FastAPI, and dynamically scales between providers.

```bash
cd backend
python -m venv venv
venv\Scripts\activate   # On Windows
pip install -r requirements.txt

# Create your .env file with your API keys:
# OPENAI_API_KEY="..."
# ANTHROPIC_API_KEY="..."
# GEMINI_API_KEY="..."

# Start the server (you will be prompted to select an AI provider)
python start_backend.py
```

### 2. Start the Desktop App (Frontend)

The frontend is built with Electron.

```bash
cd desktop-app
npm install
npm start
```

## 🛠 Tech Stack

- **Backend:** Python, FastAPI, Uvicorn, Local/Cloud LLM
- **Frontend:** Node.js, Electron
- **AI Integration:** OpenAI, Anthropic, Gemini, Ollama
