/**
 * Azure OpenAI GPT-4o Realtime Audio Chat
 * Frontend JavaScript Application
 */

class RealtimeChat {
    constructor() {
        // Socket.IO connection
        this.socket = null;

        // Audio context and processing
        this.audioContext = null;
        this.mediaStream = null;
        this.audioWorklet = null;
        this.analyser = null;

        // Audio playback
        this.audioQueue = [];
        this.isPlaying = false;
        this.playbackSampleRate = 24000;

        // State
        this.isSessionActive = false;
        this.currentAssistantMessage = null;
        this.voiceConfig = null;

        // DOM Elements
        this.elements = {
            microphoneSelect: document.getElementById('microphone-select'),
            speakerSelect: document.getElementById('speaker-select'),
            voiceSelect: document.getElementById('voice-select'),
            temperatureSlider: document.getElementById('temperature-slider'),
            temperatureValue: document.getElementById('temperature-value'),
            temperatureDescription: document.getElementById('temperature-description'),
            maxTokensSelect: document.getElementById('max-tokens-select'),
            startBtn: document.getElementById('start-btn'),
            stopBtn: document.getElementById('stop-btn'),
            connectionStatus: document.getElementById('connection-status'),
            speechStatus: document.getElementById('speech-status'),
            transcript: document.getElementById('transcript'),
            visualizerCanvas: document.getElementById('visualizer-canvas')
        };

        this.init();
    }

    async init() {
        // Load voice configuration from API
        await this.loadVoiceConfig();

        // Initialize audio devices
        await this.loadAudioDevices();

        // Setup event listeners
        this.setupEventListeners();

        // Initialize visualizer
        this.initVisualizer();

        // Connect to Socket.IO server
        this.connectSocket();
    }

    async loadVoiceConfig() {
        try {
            const response = await fetch('/api/voice-config');
            const data = await response.json();
            this.voiceConfig = data;

            // Populate voice select dropdown
            this.elements.voiceSelect.innerHTML = '';
            data.voices.forEach(voice => {
                const option = document.createElement('option');
                option.value = voice.id;
                option.textContent = `${voice.name} - ${voice.description}`;
                this.elements.voiceSelect.appendChild(option);
            });

            // Set up temperature slider with config values
            if (data.config.temperature) {
                const tempConfig = data.config.temperature;
                this.elements.temperatureSlider.min = tempConfig.min;
                this.elements.temperatureSlider.max = tempConfig.max;
                this.elements.temperatureSlider.step = tempConfig.step;
                this.elements.temperatureSlider.value = tempConfig.default;
                this.elements.temperatureValue.textContent = tempConfig.default;
                this.elements.temperatureDescription.textContent = tempConfig.description;
            }

            console.log('Voice configuration loaded:', data);
        } catch (error) {
            console.error('Error loading voice configuration:', error);
            // Fallback to default voice if API fails
            this.elements.voiceSelect.innerHTML = '<option value="alloy">Alloy - Neutral and balanced</option>';
        }
    }

    async loadAudioDevices() {
        try {
            // Request permission first
            await navigator.mediaDevices.getUserMedia({ audio: true });

            const devices = await navigator.mediaDevices.enumerateDevices();

            // Clear existing options
            this.elements.microphoneSelect.innerHTML = '';
            this.elements.speakerSelect.innerHTML = '';

            // Filter and add devices
            const audioInputs = devices.filter(d => d.kind === 'audioinput');
            const audioOutputs = devices.filter(d => d.kind === 'audiooutput');

            audioInputs.forEach(device => {
                const option = document.createElement('option');
                option.value = device.deviceId;
                option.textContent = device.label || `Microphone ${this.elements.microphoneSelect.children.length + 1}`;
                this.elements.microphoneSelect.appendChild(option);
            });

            audioOutputs.forEach(device => {
                const option = document.createElement('option');
                option.value = device.deviceId;
                option.textContent = device.label || `Speaker ${this.elements.speakerSelect.children.length + 1}`;
                this.elements.speakerSelect.appendChild(option);
            });

            if (audioInputs.length === 0) {
                this.elements.microphoneSelect.innerHTML = '<option value="">No microphones found</option>';
            }

            if (audioOutputs.length === 0) {
                this.elements.speakerSelect.innerHTML = '<option value="">Default speaker</option>';
            }

        } catch (error) {
            console.error('Error loading audio devices:', error);
            this.showError('Could not access audio devices. Please allow microphone access.');
        }
    }

    setupEventListeners() {
        this.elements.startBtn.addEventListener('click', () => this.startSession());
        this.elements.stopBtn.addEventListener('click', () => this.endSession());

        // Listen for device changes
        navigator.mediaDevices.addEventListener('devicechange', () => this.loadAudioDevices());

        // Temperature slider update
        this.elements.temperatureSlider.addEventListener('input', (e) => {
            this.elements.temperatureValue.textContent = e.target.value;
        });
    }

    connectSocket() {
        this.socket = io({
            transports: ['websocket', 'polling']
        });

        this.socket.on('connect', () => {
            console.log('Connected to server');
            this.updateConnectionStatus('connected', 'Connected');
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from server');
            this.updateConnectionStatus('disconnected', 'Disconnected');
            this.isSessionActive = false;
            this.updateButtons();
        });

        this.socket.on('connected', (data) => {
            console.log('Socket ID:', data.sid);
        });

        this.socket.on('session_created', (data) => {
            console.log('Session created:', data);
            this.clearTranscript();
            this.addSystemMessage('Session started. Speak to begin the conversation...');
        });

        this.socket.on('session_updated', (data) => {
            console.log('Session updated:', data);
        });

        this.socket.on('speech_started', () => {
            this.updateSpeechStatus(true);
            // Interrupt any ongoing playback when user starts speaking
            this.interruptPlayback();
        });

        this.socket.on('speech_stopped', () => {
            this.updateSpeechStatus(false);
        });

        this.socket.on('user_transcript', (data) => {
            this.addMessage('user', data.transcript);
        });

        this.socket.on('transcript_delta', (data) => {
            this.appendAssistantMessage(data.delta);
        });

        this.socket.on('transcript_done', (data) => {
            this.finalizeAssistantMessage(data.transcript);
        });

        this.socket.on('audio_delta', (data) => {
            this.queueAudio(data.delta);
        });

        this.socket.on('audio_done', () => {
            // Audio stream complete
        });

        this.socket.on('response_done', () => {
            this.currentAssistantMessage = null;
        });

        this.socket.on('session_ended', () => {
            this.addSystemMessage('Session ended.');
            this.isSessionActive = false;
            this.updateButtons();
        });

        this.socket.on('error', (data) => {
            console.error('Error:', data);
            this.showError(data.message || data.error?.message || 'An error occurred');
        });
    }

    async startSession() {
        if (this.isSessionActive) return;

        try {
            this.updateConnectionStatus('connecting', 'Connecting...');

            // Initialize audio context
            this.audioContext = new AudioContext({ sampleRate: 24000 });

            // Get selected microphone
            const microphoneId = this.elements.microphoneSelect.value;
            const constraints = {
                audio: {
                    deviceId: microphoneId ? { exact: microphoneId } : undefined,
                    sampleRate: 24000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true
                }
            };

            this.mediaStream = await navigator.mediaDevices.getUserMedia(constraints);

            // Setup audio processing
            await this.setupAudioProcessing();

            // Start the session with the backend
            const voice = this.elements.voiceSelect.value;
            const temperature = parseFloat(this.elements.temperatureSlider.value);
            const maxTokens = this.elements.maxTokensSelect.value;

            this.socket.emit('start_session', {
                voice,
                temperature,
                max_response_output_tokens: maxTokens === 'inf' ? 'inf' : parseInt(maxTokens)
            });

            this.isSessionActive = true;
            this.updateButtons();

        } catch (error) {
            console.error('Error starting session:', error);
            this.showError('Failed to start session: ' + error.message);
            this.updateConnectionStatus('disconnected', 'Failed to connect');
        }
    }

    async setupAudioProcessing() {
        const source = this.audioContext.createMediaStreamSource(this.mediaStream);

        // Create analyser for visualization
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 256;
        source.connect(this.analyser);

        // Setup audio worklet for processing
        await this.audioContext.audioWorklet.addModule('/static/audio-processor.js');

        this.audioWorklet = new AudioWorkletNode(this.audioContext, 'audio-processor');

        this.audioWorklet.port.onmessage = (event) => {
            if (event.data.type === 'audio' && this.isSessionActive) {
                // Convert Float32Array to Int16Array (PCM16)
                const float32Data = event.data.audio;
                const int16Data = this.floatTo16BitPCM(float32Data);

                // Convert to base64
                const base64Audio = this.arrayBufferToBase64(int16Data.buffer);

                // Send to backend
                this.socket.emit('send_audio', { audio: base64Audio });
            }
        };

        source.connect(this.audioWorklet);
        this.audioWorklet.connect(this.audioContext.destination);

        // Start visualization
        this.startVisualization();
    }

    floatTo16BitPCM(float32Array) {
        const int16Array = new Int16Array(float32Array.length);
        for (let i = 0; i < float32Array.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Array[i]));
            int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        return int16Array;
    }

    arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    base64ToArrayBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    queueAudio(base64Audio) {
        const arrayBuffer = this.base64ToArrayBuffer(base64Audio);
        const int16Array = new Int16Array(arrayBuffer);

        // Convert Int16 to Float32
        const float32Array = new Float32Array(int16Array.length);
        for (let i = 0; i < int16Array.length; i++) {
            float32Array[i] = int16Array[i] / 32768.0;
        }

        this.audioQueue.push(float32Array);

        if (!this.isPlaying) {
            this.playNextAudio();
        }
    }

    async playNextAudio() {
        if (this.audioQueue.length === 0) {
            this.isPlaying = false;
            return;
        }

        this.isPlaying = true;

        const audioData = this.audioQueue.shift();

        try {
            const audioBuffer = this.audioContext.createBuffer(1, audioData.length, this.playbackSampleRate);
            audioBuffer.getChannelData(0).set(audioData);

            const source = this.audioContext.createBufferSource();
            source.buffer = audioBuffer;

            // Apply speaker selection if supported
            const speakerId = this.elements.speakerSelect.value;
            if (speakerId && this.audioContext.setSinkId) {
                try {
                    await this.audioContext.setSinkId(speakerId);
                } catch (e) {
                    console.warn('Could not set audio output device:', e);
                }
            }

            source.connect(this.audioContext.destination);

            source.onended = () => {
                this.playNextAudio();
            };

            source.start();
        } catch (error) {
            console.error('Error playing audio:', error);
            this.playNextAudio();
        }
    }

    interruptPlayback() {
        this.audioQueue = [];
        this.isPlaying = false;
    }

    endSession() {
        if (!this.isSessionActive) return;

        // Stop audio processing
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
        }

        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }

        // Clear audio queue
        this.audioQueue = [];
        this.isPlaying = false;

        // End session on backend
        this.socket.emit('end_session', {});

        this.isSessionActive = false;
        this.updateButtons();
        this.updateConnectionStatus('connected', 'Connected');
        this.updateSpeechStatus(false);
    }

    // UI Update Methods
    updateConnectionStatus(status, text) {
        const dot = this.elements.connectionStatus.querySelector('.status-dot');
        const textEl = this.elements.connectionStatus.querySelector('.status-text');

        dot.className = 'status-dot ' + status;
        textEl.textContent = text;
    }

    updateSpeechStatus(isActive) {
        const icon = this.elements.speechStatus.querySelector('.speech-icon');
        const text = this.elements.speechStatus.querySelector('.status-text');

        if (isActive) {
            icon.classList.add('active');
            text.textContent = 'Listening...';
        } else {
            icon.classList.remove('active');
            text.textContent = 'Not listening';
        }
    }

    updateButtons() {
        this.elements.startBtn.disabled = this.isSessionActive;
        this.elements.stopBtn.disabled = !this.isSessionActive;
    }

    clearTranscript() {
        this.elements.transcript.innerHTML = '';
    }

    addMessage(role, text) {
        // Remove placeholder if exists
        const placeholder = this.elements.transcript.querySelector('.transcript-placeholder');
        if (placeholder) placeholder.remove();

        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;

        const label = document.createElement('div');
        label.className = 'message-label';
        label.textContent = role === 'user' ? 'You' : 'Assistant';

        const content = document.createElement('div');
        content.className = 'message-content';
        content.textContent = text;

        messageDiv.appendChild(label);
        messageDiv.appendChild(content);

        this.elements.transcript.appendChild(messageDiv);
        this.scrollToBottom();
    }

    addSystemMessage(text) {
        // Remove placeholder if exists
        const placeholder = this.elements.transcript.querySelector('.transcript-placeholder');
        if (placeholder) placeholder.remove();

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message system';
        messageDiv.innerHTML = `<div class="message-content" style="background: rgba(255,255,255,0.1); max-width: 100%; text-align: center; color: #888;">${text}</div>`;

        this.elements.transcript.appendChild(messageDiv);
        this.scrollToBottom();
    }

    appendAssistantMessage(delta) {
        if (!this.currentAssistantMessage) {
            // Remove placeholder if exists
            const placeholder = this.elements.transcript.querySelector('.transcript-placeholder');
            if (placeholder) placeholder.remove();

            // Create new message element
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message assistant';

            const label = document.createElement('div');
            label.className = 'message-label';
            label.textContent = 'Assistant';

            const content = document.createElement('div');
            content.className = 'message-content';
            content.textContent = '';

            messageDiv.appendChild(label);
            messageDiv.appendChild(content);

            this.elements.transcript.appendChild(messageDiv);
            this.currentAssistantMessage = content;
        }

        this.currentAssistantMessage.textContent += delta;
        this.scrollToBottom();
    }

    finalizeAssistantMessage(fullText) {
        if (this.currentAssistantMessage) {
            this.currentAssistantMessage.textContent = fullText;
        }
        this.currentAssistantMessage = null;
    }

    showError(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.textContent = message;

        this.elements.transcript.appendChild(errorDiv);
        this.scrollToBottom();

        // Auto-remove after 10 seconds
        setTimeout(() => {
            errorDiv.remove();
        }, 10000);
    }

    scrollToBottom() {
        this.elements.transcript.scrollTop = this.elements.transcript.scrollHeight;
    }

    // Audio Visualization
    initVisualizer() {
        this.visualizerCtx = this.elements.visualizerCanvas.getContext('2d');
        this.resizeVisualizer();

        window.addEventListener('resize', () => this.resizeVisualizer());
    }

    resizeVisualizer() {
        const container = this.elements.visualizerCanvas.parentElement;
        this.elements.visualizerCanvas.width = container.clientWidth - 32;
        this.elements.visualizerCanvas.height = container.clientHeight - 32;
    }

    startVisualization() {
        const draw = () => {
            if (!this.analyser || !this.isSessionActive) {
                this.drawIdleVisualizer();
                return;
            }

            requestAnimationFrame(draw);

            const bufferLength = this.analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);
            this.analyser.getByteFrequencyData(dataArray);

            const canvas = this.elements.visualizerCanvas;
            const ctx = this.visualizerCtx;
            const width = canvas.width;
            const height = canvas.height;

            ctx.fillStyle = 'rgba(22, 33, 62, 0.3)';
            ctx.fillRect(0, 0, width, height);

            const barWidth = (width / bufferLength) * 2.5;
            let x = 0;

            for (let i = 0; i < bufferLength; i++) {
                const barHeight = (dataArray[i] / 255) * height;

                const gradient = ctx.createLinearGradient(0, height - barHeight, 0, height);
                gradient.addColorStop(0, '#00d4ff');
                gradient.addColorStop(1, '#0078d4');

                ctx.fillStyle = gradient;
                ctx.fillRect(x, height - barHeight, barWidth, barHeight);

                x += barWidth + 1;
            }
        };

        draw();
    }

    drawIdleVisualizer() {
        const canvas = this.elements.visualizerCanvas;
        const ctx = this.visualizerCtx;
        const width = canvas.width;
        const height = canvas.height;

        ctx.fillStyle = '#16213e';
        ctx.fillRect(0, 0, width, height);

        ctx.strokeStyle = '#333';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(0, height / 2);
        ctx.lineTo(width, height / 2);
        ctx.stroke();
    }
}

// Initialize the application when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.realtimeChat = new RealtimeChat();
});
