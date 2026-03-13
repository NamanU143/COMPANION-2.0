const face = document.getElementById('assistant-face');
const audioPlayer = document.getElementById('audio-player');
const minimizeBtn = document.getElementById('minimize-btn');
const { ipcRenderer } = require('electron');

const BACKEND_URL = 'http://127.0.0.1:8000';

let isListening = false;
let recognition;
let randomBlinkTimeout;

// Random blinking logic
function scheduleNextBlink() {
    // Random time between 2 to 6 seconds
    const delay = Math.random() * 4000 + 2000;
    
    randomBlinkTimeout = setTimeout(() => {
        // Only blink if not already transitioning or speaking heavily
        if (!face.classList.contains('speaking')) {
            face.classList.add('blinking');
            
            // Blink duration is very fast (150ms)
            setTimeout(() => {
                face.classList.remove('blinking');
                scheduleNextBlink(); // Schedule the next one
            }, 150);
        } else {
            // If speaking, skip this blink and schedule next
            scheduleNextBlink();
        }
    }, delay);
}

// Start the blinking cycle
scheduleNextBlink();

let mediaRecorder;
let audioChunks = [];

// VAD Constants
const SILENCE_THRESHOLD = 5; // Adjust this based on mic sensitivity (0-255)
const SILENCE_DURATION_MS = 1500; // Time of silence before sending

let audioContext;
let analyser;
let micStream;
let vadAnimationFrame;
let isRecordingVAD = false;
let silenceStartMs = 0;
let isMuted = false;

// Initialize continuous microphone monitoring
async function startVAD() {
    try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        
        const source = audioContext.createMediaStreamSource(micStream);
        source.connect(analyser);
        
        monitorVolume();
        
    } catch(err) {
        console.error("Microphone access error:", err);
        face.classList.remove('listening');
    }
}

function monitorVolume() {
    vadAnimationFrame = requestAnimationFrame(monitorVolume);
    
    if (isMuted) return; // Don't listen while bot is speaking or processing
    
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(dataArray);
    
    // Calculate RMS (Root Mean Square) volume approximation
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
        sum += dataArray[i];
    }
    const averageVolume = sum / dataArray.length;
    
    if (averageVolume > SILENCE_THRESHOLD) {
        // Person is speaking
        silenceStartMs = 0; // reset silence timer
        
        if (!isRecordingVAD) {
            startBuffering();
        }
    } else {
        // Silence detected
        if (isRecordingVAD) {
            if (silenceStartMs === 0) {
                silenceStartMs = Date.now();
            } else if (Date.now() - silenceStartMs > SILENCE_DURATION_MS) {
                // Silence held for long enough, stop and flush
                stopBufferingAndSend();
            }
        }
    }
}

function startBuffering() {
    isRecordingVAD = true;
    audioChunks = [];
    
    face.classList.add('listening');
    face.classList.remove('speaking', 'idle');
    console.log("VAD: Voice detected, started recording.");

    mediaRecorder = new MediaRecorder(micStream, { mimeType: 'audio/webm' });
    mediaRecorder.ondataavailable = e => {
        if (e.data.size > 0) audioChunks.push(e.data);
    };
    
    mediaRecorder.start();
}

function stopBufferingAndSend() {
    console.log("VAD: Silence detected, stopping recording and sending.");
    isRecordingVAD = false;
    isMuted = true; // Mute mic so we don't hear our own thinking/speaking noise
    silenceStartMs = 0;
    
    face.classList.remove('listening');
    face.classList.add('thinking');
    
    mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        audioChunks = [];
        
        const reader = new FileReader();
        reader.readAsDataURL(audioBlob);
        reader.onloadend = async () => {
            const base64Audio = reader.result.split(',')[1];
            await sendToBackend(null, base64Audio);
            face.classList.remove('thinking');
        };
    };
    
    mediaRecorder.stop();
}

// Start VAD automatically on load
window.addEventListener('DOMContentLoaded', () => {
    startVAD();
});

// Click eyes to manually interrupt/send (optional fallback)
const eyesContainer = document.querySelector('.eyes');
eyesContainer.addEventListener('click', (e) => {
    console.log('Eyes clicked! Manual intervention.');
    if (isRecordingVAD) {
        stopBufferingAndSend();
    } else {
        // If it was idle, kickstart it manually
        if (!isMuted) startBuffering();
    }
});

minimizeBtn.addEventListener('click', () => {
    ipcRenderer.send('minimize-window');
});

async function sendToBackend(message = null, audioBase64 = null) {
    try {
        const bodyData = {};
        if (message) bodyData.message = message;
        if (audioBase64) bodyData.audio_base64 = audioBase64;

        const response = await fetch(`${BACKEND_URL}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(bodyData)
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        console.log('AI Response:', data.text);
        
        // Since audio playback is driven fully by the Python backend via `sounddevice`
        // we no longer have an `audio_url` or an `<audio>` element duration event to tap into.
        // We will mock the duration based on an estimated words-per-minute or raw character length.
        
        // Roughly ~15 characters per second of audio for a fast robotic voice (or 60ms per char)
        const msPerChar = 60; 
        playAudioWithEmotions(data.segments, data.text.length, msPerChar);
    } catch (error) {
        console.error('Error sending message to backend:', error);
    }
}

// Global reference to timeouts so they can be cleared
let emotionTimeouts = [];

function playAudioWithEmotions(segments, totalLength, msPerChar) {
    // Clear any previous timeouts
    emotionTimeouts.forEach(clearTimeout);
    emotionTimeouts = [];
    
    // Reset face
    face.className = 'cube-face speaking'; // Base class + speaking pulse
    
    // We simulate the duration of the entire audio
    const totalDurationMs = totalLength * msPerChar;
    let cumulativeTime = 0;

    segments.forEach((segment) => {
        const duration = segment.text.length * msPerChar;
        const emotion = segment.emotion.toLowerCase();
        
        // Schedule the emotion change
        const timeout = setTimeout(() => {
            // Keep base classes, then add the specific emotion
            face.className = `cube-face speaking ${emotion}`;
            console.log(`Setting emotion: ${emotion} for text: "${segment.text}"`);
        }, cumulativeTime);
        
        emotionTimeouts.push(timeout);
        cumulativeTime += duration;
    });

    // Remove speaking animation and emotions when simulated audio finishes
    const endTimeout = setTimeout(() => {
        face.className = 'cube-face'; // Reset to idle
        emotionTimeouts.forEach(clearTimeout);
        emotionTimeouts = [];
        
        // Unmute VAD to listen for user again
        isMuted = false;
        console.log("VAD: Unmuted, listening for user again.");
    }, totalDurationMs);
    
    emotionTimeouts.push(endTimeout);
}
