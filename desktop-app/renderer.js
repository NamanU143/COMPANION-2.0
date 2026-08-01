const { ipcRenderer } = require('electron');

const BACKEND_WS = 'ws://127.0.0.1:8000/ws';
const BACKEND_HTTP = 'http://127.0.0.1:8000';

// ---- DOM ------------------------------------------------------------------
const panel = document.getElementById('panel');
const foxCanvas = document.getElementById('fox-canvas');
const statusEl = document.getElementById('status');
const capUser = document.getElementById('caption-user');
const capMilo = document.getElementById('caption-milo');
const muteBtn = document.getElementById('mute-btn');
const minimizeBtn = document.getElementById('minimize-btn');
const closeBtn = document.getElementById('close-btn');
const composer = document.getElementById('composer');
const textInput = document.getElementById('text-input');
const voiceSelect = document.getElementById('voice-select');

let currentStyle = 'milo';

// Populate the voice dropdown from the backend.
async function loadVoices() {
    try {
        const res = await fetch(`${BACKEND_HTTP}/voices`);
        const data = await res.json();
        voiceSelect.innerHTML = '';
        (data.voices || []).forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.id;
            opt.textContent = v.label;
            voiceSelect.appendChild(opt);
        });
        voiceSelect.value = currentStyle;
    } catch (e) {
        console.warn('could not load voices', e);
    }
}
voiceSelect && voiceSelect.addEventListener('change', () => { currentStyle = voiceSelect.value; });

const STATUS_TEXT = {
    listening: 'Listening…',
    recording: 'Listening…',
    thinking: 'Thinking…',
    speaking: 'Speaking…',
    muted: 'Muted',
};

// ---- Conversation state ---------------------------------------------------
let state = 'listening';
let turnCounter = 0;
let playbackTurn = -1;
let isMuted = false;

function setState(s) {
    if (s === 'speaking' && state !== 'speaking') speakingSince = Date.now();
    state = s;
    panel.dataset.state = (s === 'recording') ? 'listening' : s;
    statusEl.textContent = STATUS_TEXT[s] || '';
}
function setEmotion(emotion) {
    foxEmotion = (emotion || 'neutral').toLowerCase();
}

// ---- Fox avatar (animated pixel canvas) -----------------------------------
let foxEmotion = 'neutral';
let foxMouth = 0;
let foxBlink = false;

// Blink on a random cadence.
function scheduleBlink() {
    const delay = Math.random() * 4000 + 2500;
    setTimeout(() => {
        foxBlink = true;
        setTimeout(() => { foxBlink = false; }, 120);
        scheduleBlink();
    }, delay);
}
scheduleBlink();

// Render loop: emotion by state, lip-sync mouth from playback, idle bob.
function foxLoop() {
    requestAnimationFrame(foxLoop);
    let target = 0;
    if (state === 'speaking' && playAnalyser) {
        playAnalyser.getByteTimeDomainData(lipData);
        let peak = 0;
        for (let i = 0; i < lipData.length; i++) {
            const v = Math.abs(lipData[i] - 128) / 128;
            if (v > peak) peak = v;
        }
        target = Math.min(1, peak * 1.9);
    }
    foxMouth += (target - foxMouth) * 0.4;

    let exp = foxEmotion;
    if (state === 'thinking') exp = 'thinking';
    else if (state === 'listening' || state === 'muted') exp = 'neutral';

    if (typeof renderFox === 'function') {
        renderFox(foxCanvas, { emotion: exp, mouthOpen: foxMouth, blink: foxBlink });
    }
    const bob = Math.sin(Date.now() / 650) * 2.2;
    foxCanvas.style.transform = `translateY(${bob.toFixed(2)}px)`;
}
requestAnimationFrame(foxLoop);

// ---- Captions -------------------------------------------------------------
function showUserCaption(text) {
    capUser.textContent = text;
    capUser.classList.toggle('show', !!text);
}
function resetMiloCaption() { capMilo.textContent = ''; capMilo.classList.remove('show'); }
function appendMiloCaption(text) {
    capMilo.textContent = (capMilo.textContent + ' ' + text).trim();
    capMilo.classList.add('show');
}

// ---- WebSocket ------------------------------------------------------------
let ws;
function connectWS() {
    ws = new WebSocket(BACKEND_WS);
    ws.onopen = () => console.log('[WS] connected');
    ws.onclose = () => { console.log('[WS] closed, retry 2s'); setTimeout(connectWS, 2000); };
    ws.onerror = (e) => console.error('[WS] error', e);
    ws.onmessage = (ev) => handleServerMessage(JSON.parse(ev.data));
}
function wsSend(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function handleServerMessage(m) {
    if (typeof m.turn === 'number' && m.turn < playbackTurn) return; // stale (post-bargein)
    switch (m.type) {
        case 'transcript':
            showUserCaption(m.text);
            resetMiloCaption();
            break;
        case 'segment':
            appendMiloCaption(m.text);
            break;
        case 'audio':
            if (m.turn === playbackTurn) enqueueAudio(m);
            break;
        case 'turn_end':
            if (m.turn === playbackTurn) markTurnComplete();
            break;
        case 'ignored':
            // Voice heard but no wake word ("Hey Milo") and not mid-conversation.
            console.log('[WS] ignored (no wake word):', m.text);
            break;
        case 'interrupted':
            console.log('[WS] interrupted', m.turn);
            break;
        case 'error':
            console.error('[WS] server error', m.message);
            markTurnComplete();
            break;
    }
}

// ---- Playback (Web Audio) + lip-sync -------------------------------------
let playCtx, playAnalyser, lipData;
let nextPlayTime = 0;
let activeSources = [];
let turnEnded = false;

function ensurePlayCtx() {
    if (!playCtx) {
        playCtx = new (window.AudioContext || window.webkitAudioContext)();
        playAnalyser = playCtx.createAnalyser();
        playAnalyser.fftSize = 256;
        playAnalyser.connect(playCtx.destination);
        lipData = new Uint8Array(playAnalyser.frequencyBinCount);
    }
    return playCtx;
}

function enqueueAudio(m) {
    const ctx = ensurePlayCtx();
    const raw = atob(m.data);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    const pcm = new Int16Array(bytes.buffer);
    const f32 = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) f32[i] = pcm[i] / 32768;

    const buffer = ctx.createBuffer(1, f32.length, m.sample_rate);
    buffer.getChannelData(0).set(f32);
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(playAnalyser);

    const startAt = Math.max(ctx.currentTime, nextPlayTime);
    src.start(startAt);
    nextPlayTime = startAt + buffer.duration;

    if (state !== 'speaking') setState('speaking');
    const emotion = (m.emotion || 'neutral');
    const delayMs = Math.max(0, (startAt - ctx.currentTime) * 1000);
    setTimeout(() => { if (state === 'speaking') setEmotion(emotion); }, delayMs);

    activeSources.push(src);
    src.onended = () => {
        activeSources = activeSources.filter(s => s !== src);
        if (activeSources.length === 0 && turnEnded) finishSpeaking();
    };
}

function markTurnComplete() {
    turnEnded = true;
    if (activeSources.length === 0) finishSpeaking();
}
function finishSpeaking() {
    turnEnded = false;
    nextPlayTime = 0;
    setEmotion('neutral');
    setState(isMuted ? 'muted' : 'listening');
}
function stopPlayback() {
    activeSources.forEach(s => { try { s.stop(); } catch (e) {} });
    activeSources = [];
    nextPlayTime = 0;
    turnEnded = false;
}

// ---- Mic + VAD ------------------------------------------------------------
const ONSET_THRESHOLD = 14;
const BARGEIN_THRESHOLD = 38;     // high bar so Milo's own echo doesn't self-interrupt
const END_SILENCE_MS = 550;       // snappier turn-end (was 1000)
const BARGEIN_SUSTAIN_MS = 450;   // require sustained speech to interrupt
const BARGEIN_GRACE_MS = 700;     // ignore mic right after Milo starts (echo settles)
let speakingSince = 0;

let micStream, micCtx, analyser, dataArray;
let recorder, recordedChunks = [];
let silenceStart = 0, speechStart = 0;

async function startMic() {
    try {
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
        });
        micCtx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = micCtx.createAnalyser();
        analyser.fftSize = 512;
        dataArray = new Uint8Array(analyser.frequencyBinCount);
        micCtx.createMediaStreamSource(micStream).connect(analyser);
        requestAnimationFrame(monitor);
        console.log('[mic] open');
    } catch (err) {
        console.error('Microphone error:', err);
        statusEl.textContent = 'Mic blocked';
    }
}

function volume() {
    analyser.getByteFrequencyData(dataArray);
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
    return sum / dataArray.length;
}

function monitor() {
    requestAnimationFrame(monitor);
    if (!analyser || isMuted) return;
    const vol = volume();
    const now = Date.now();

    if (state === 'speaking') {
        // Grace period right after Milo starts talking — let echo settle.
        if (now - speakingSince < BARGEIN_GRACE_MS) { speechStart = 0; return; }
        if (vol > BARGEIN_THRESHOLD) {
            if (speechStart === 0) speechStart = now;
            else if (now - speechStart > BARGEIN_SUSTAIN_MS) bargeIn();
        } else speechStart = 0;
        return;
    }
    if (state === 'thinking') return;

    if (vol > ONSET_THRESHOLD) {
        silenceStart = 0;
        if (state === 'listening') startRecording();
    } else if (state === 'recording') {
        if (silenceStart === 0) silenceStart = now;
        else if (now - silenceStart > END_SILENCE_MS) endRecordingAndSend();
    }
}

function startRecording() {
    setState('recording');
    speechStart = 0;
    recordedChunks = [];
    recorder = new MediaRecorder(micStream, { mimeType: 'audio/webm' });
    recorder.ondataavailable = e => { if (e.data.size > 0) recordedChunks.push(e.data); };
    recorder.start();
}

function endRecordingAndSend() {
    setState('thinking');
    silenceStart = 0;
    const myTurn = ++turnCounter;
    playbackTurn = myTurn;
    turnEnded = false;
    recorder.onstop = () => {
        const blob = new Blob(recordedChunks, { type: 'audio/webm' });
        recordedChunks = [];
        const reader = new FileReader();
        reader.onloadend = () => wsSend({ type: 'audio', turn: myTurn, data: reader.result.split(',')[1], style: currentStyle });
        reader.readAsDataURL(blob);
    };
    recorder.stop();
}

function bargeIn() {
    console.log('[bargein]');
    stopPlayback();
    wsSend({ type: 'interrupt', turn: playbackTurn });
    playbackTurn = turnCounter + 1;
    speechStart = 0;
    setState('listening');
    startRecording();
}

// ---- Text composer --------------------------------------------------------
composer.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = textInput.value.trim();
    if (!text) return;
    textInput.value = '';
    const myTurn = ++turnCounter;
    playbackTurn = myTurn;
    turnEnded = false;
    showUserCaption(text);
    resetMiloCaption();
    setState('thinking');
    wsSend({ type: 'text', turn: myTurn, text, style: currentStyle });
});

// ---- Controls -------------------------------------------------------------
muteBtn.addEventListener('click', () => {
    isMuted = !isMuted;
    muteBtn.classList.toggle('muted', isMuted);
    muteBtn.textContent = isMuted ? '🔇' : '🎙️';
    if (isMuted) {
        if (state === 'recording' && recorder) { try { recorder.stop(); } catch (e) {} }
        setState('muted');
    } else if (state === 'muted') {
        setState('listening');
    }
});
minimizeBtn.addEventListener('click', () => ipcRenderer.send('minimize-window'));
closeBtn.addEventListener('click', () => ipcRenderer.send('close-window'));

// ---- Boot -----------------------------------------------------------------
window.addEventListener('DOMContentLoaded', () => {
    setState('listening');
    setEmotion('neutral');
    loadVoices();
    connectWS();
    startMic();
});
