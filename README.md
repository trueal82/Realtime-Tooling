# Azure OpenAI GPT-4o Realtime Audio Chat

A real-time voice conversation application powered by Azure OpenAI's GPT-4o Realtime API. This application enables natural voice interactions with AI, featuring live transcription, audio visualization, and configurable audio devices.

![Python](https://img.shields.io/badge/Python-3.14+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## Features

- 🎙️ **Real-time Voice Conversation** - Talk naturally with GPT-4o using your microphone
- 📝 **Live Transcription** - See both your speech and AI responses transcribed in real-time
- 🔊 **Audio Device Selection** - Choose your preferred microphone and speaker
- 🗣️ **Multiple AI Voices** - Select from 8 voice options (Alloy, Ash, Ballad, Coral, Echo, Sage, Shimmer, Verse)
- 🎚️ **Voice Configuration** - Adjust temperature and response length settings
- 🎵 **Audio Visualization** - Visual feedback of audio input levels
- 🔄 **Server-side VAD** - Automatic voice activity detection for natural conversations
- 🛑 **Interruption Support** - Interrupt the AI mid-response by speaking

## Prerequisites

- Python 3.14 or higher
- [uv](https://docs.astral.sh/uv/) - Fast Python package installer and resolver
- An Azure OpenAI resource with GPT-4o Realtime model deployed
- A modern web browser with microphone access (Chrome, Firefox, Edge recommended)

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Realtime-Tooling
   ```

2. **Install uv** (if not already installed)
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Install dependencies**
   ```bash
   uv sync
   ```

4. **Configure environment variables**
   ```bash
   cp template.env .env
   ```
   
   Edit `.env` and fill in your Azure OpenAI credentials:
   ```env
   AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
   AZURE_OPENAI_API_KEY=your-api-key-here
   AZURE_OPENAI_DEPLOYMENT=gpt-4o-realtime-preview
   AZURE_OPENAI_API_VERSION=2024-10-01-preview
   ```

## Usage

1. **Start the server**
   ```bash
   uv run python main.py
   ```

2. **Open the application**
   
   Navigate to [http://localhost:8080](http://localhost:8080) in your web browser.

3. **Configure audio devices**
   - Select your preferred microphone from the dropdown
   - Select your preferred speaker/output device
   - Choose an AI voice from 8 options
   - Adjust temperature (creativity) and max response tokens as needed

4. **Start a conversation**
   - Click "Start Session" to begin
   - Allow microphone access when prompted
   - Start speaking - the AI will respond automatically
   - Click "End Session" when finished

## Testing

Run the test suite:

```bash
uv run pytest tests/ -v
```

Run tests with coverage:

```bash
uv run pytest tests/ --cov=. --cov-report=term-missing
```

## Project Structure

```
Realtime-Tooling/
├── main.py                 # Backend server (Socket.IO + Azure OpenAI)
├── pyproject.toml          # Python project configuration
├── template.env            # Environment variables template
├── README.md               # This file
├── .gitignore              # Git ignore rules
├── static/
│   ├── index.html          # Main HTML page
│   ├── styles.css          # CSS styles
│   ├── app.js              # Frontend JavaScript application
│   ├── audio-processor.js  # AudioWorklet for audio processing
│   └── socket.io.min.js    # Socket.IO client library (bundled)
├── tests/
│   ├── test_main.py        # Backend tests
│   └── test_static.py      # Frontend file tests
└── .github/
    └── workflows/
        └── tests.yml       # GitHub Actions CI workflow
```

## Architecture

```
┌─────────────────┐     Socket.IO      ┌─────────────────┐     WebSocket     ┌──────────────────┐
│                 │ ◄────────────────► │                 │ ◄───────────────► │                  │
│  Web Browser    │    Audio/Events    │  Python Server  │   Audio/Events   │  Azure OpenAI    │
│  (Frontend)     │                    │  (main.py)      │                  │  Realtime API    │
│                 │                    │                 │                  │                  │
└─────────────────┘                    └─────────────────┘                  └──────────────────┘
```

### Data Flow

1. **User speaks** → Microphone captures audio
2. **Audio processed** → AudioWorklet converts to PCM16, base64 encoded
3. **Sent to backend** → Socket.IO transmits audio chunks
4. **Forwarded to Azure** → Backend sends to Azure OpenAI Realtime API
5. **AI processes** → Azure OpenAI generates response
6. **Response streamed** → Audio and transcript sent back through the chain
7. **Played to user** → Browser plays audio and displays transcript

## Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint URL | (required) |
| `AZURE_OPENAI_API_KEY` | API key for authentication | (required) |
| `AZURE_OPENAI_DEPLOYMENT` | Model deployment name | `gpt-4o-realtime-preview` |
| `AZURE_OPENAI_API_VERSION` | API version | `2024-10-01-preview` |

### Session Configuration

The session is configured with the following defaults (can be adjusted in the UI or `main.py`):

- **Modalities**: Text and Audio
- **Input/Output Audio Format**: PCM16 at 24kHz
- **Transcription Model**: Whisper-1
- **Turn Detection**: Server-side VAD with 500ms silence threshold
- **Temperature**: 0.8 (range: 0.6 - 1.2)
- **Max Response Tokens**: 4096 (options: 1024, 2048, 4096, or unlimited)

## Troubleshooting

### Common Issues

1. **"Azure OpenAI credentials not configured"**
   - Ensure `.env` file exists with valid credentials
   - Check that the endpoint URL includes the full path (e.g., `https://...openai.azure.com/`)

2. **Microphone not detected**
   - Allow microphone permissions in your browser
   - Check that your microphone is properly connected
   - Try refreshing the page after granting permissions

3. **No audio output**
   - Check your speaker/output device selection
   - Ensure browser audio is not muted
   - Verify that audio autoplay is allowed in your browser

4. **Connection errors**
   - Verify your Azure OpenAI deployment is active
   - Check that the deployment name matches exactly
   - Ensure your API key has proper permissions

### Debug Mode

Check the browser console (F12) and terminal output for detailed error messages.

## Browser Compatibility

| Browser | Status |
|---------|--------|
| Chrome 90+ | ✅ Fully supported |
| Firefox 90+ | ✅ Fully supported |
| Edge 90+ | ✅ Fully supported |
| Safari 15+ | ⚠️ Limited (AudioWorklet support varies) |

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- [Azure OpenAI Service](https://azure.microsoft.com/en-us/products/ai-services/openai-service)
- [uv](https://docs.astral.sh/uv/) - Fast Python package installer
- [Socket.IO](https://socket.io/)
- [aiohttp](https://docs.aiohttp.org/)
