"""
Azure OpenAI GPT-4o Realtime Audio Chat Backend
Uses Socket.IO for real-time communication with the frontend
and WebSockets to connect to Azure OpenAI Realtime API
"""

import asyncio
import json
import os
from pathlib import Path

from typing import Any

import socketio
from aiohttp import web
from dotenv import load_dotenv
import websockets

# Load environment variables
load_dotenv()

# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-realtime-preview")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-01-preview")

# Available voices for GPT-4o Realtime
# Reference: https://learn.microsoft.com/en-us/azure/ai-services/openai/realtime-audio-reference
AVAILABLE_VOICES = [
    {"id": "alloy", "name": "Alloy", "description": "Neutral and balanced"},
    {"id": "ash", "name": "Ash", "description": "Warm and conversational"},
    {"id": "ballad", "name": "Ballad", "description": "Expressive and dramatic"},
    {"id": "coral", "name": "Coral", "description": "Clear and informative"},
    {"id": "echo", "name": "Echo", "description": "Smooth and calm"},
    {"id": "sage", "name": "Sage", "description": "Wise and thoughtful"},
    {"id": "shimmer", "name": "Shimmer", "description": "Bright and energetic"},
    {"id": "verse", "name": "Verse", "description": "Versatile and adaptive"},
]

# Voice configuration options
VOICE_CONFIG = {
    "temperature": {
        "min": 0.6,
        "max": 1.2,
        "default": 0.8,
        "step": 0.1,
        "description": "Controls randomness in responses. Lower values are more focused, higher values are more creative."
    },
    "max_response_output_tokens": {
        "min": 1,
        "max": 4096,
        "default": 4096,
        "description": "Maximum number of tokens in the response. Use 'inf' for unlimited."
    }
}

# Create Socket.IO server
sio = socketio.AsyncServer(
    async_mode='aiohttp',
    cors_allowed_origins='*'
)

# Create aiohttp application
app = web.Application()
sio.attach(app)

# Store active connections
active_connections: dict[str, Any] = {}
active_tasks: dict[str, asyncio.Task] = {}


def get_realtime_url() -> str:
    """Construct the Azure OpenAI Realtime WebSocket URL"""
    # Remove trailing slash if present
    endpoint = AZURE_OPENAI_ENDPOINT.rstrip('/')
    # Extract the base URL (remove https://)
    if endpoint.startswith('https://'):
        endpoint = endpoint[8:]
    elif endpoint.startswith('http://'):
        endpoint = endpoint[7:]

    return f"wss://{endpoint}/openai/realtime?api-version={AZURE_OPENAI_API_VERSION}&deployment={AZURE_OPENAI_DEPLOYMENT}"


async def handle_realtime_messages(sid: str, ws: Any):
    """Handle incoming messages from Azure OpenAI Realtime API"""
    try:
        async for message in ws:
            data = json.loads(message)
            event_type = data.get("type", "")

            # Handle different event types
            if event_type == "session.created":
                await sio.emit('session_created', data, room=sid)
                print(f"[{sid}] Session created")

            elif event_type == "session.updated":
                await sio.emit('session_updated', data, room=sid)
                print(f"[{sid}] Session updated")

            elif event_type == "conversation.item.created":
                await sio.emit('conversation_item_created', data, room=sid)

            elif event_type == "response.created":
                await sio.emit('response_created', data, room=sid)

            elif event_type == "response.output_item.added":
                await sio.emit('response_output_item_added', data, room=sid)

            elif event_type == "response.content_part.added":
                await sio.emit('response_content_part_added', data, room=sid)

            elif event_type == "response.audio_transcript.delta":
                # Send transcript delta to frontend
                await sio.emit('transcript_delta', {
                    'role': 'assistant',
                    'delta': data.get('delta', '')
                }, room=sid)

            elif event_type == "response.audio.delta":
                # Send audio delta to frontend
                await sio.emit('audio_delta', {
                    'delta': data.get('delta', '')
                }, room=sid)

            elif event_type == "response.audio.done":
                await sio.emit('audio_done', {}, room=sid)

            elif event_type == "response.audio_transcript.done":
                await sio.emit('transcript_done', {
                    'role': 'assistant',
                    'transcript': data.get('transcript', '')
                }, room=sid)

            elif event_type == "input_audio_buffer.speech_started":
                await sio.emit('speech_started', data, room=sid)
                print(f"[{sid}] Speech started")

            elif event_type == "input_audio_buffer.speech_stopped":
                await sio.emit('speech_stopped', data, room=sid)
                print(f"[{sid}] Speech stopped")

            elif event_type == "conversation.item.input_audio_transcription.completed":
                # User's speech transcription
                await sio.emit('user_transcript', {
                    'role': 'user',
                    'transcript': data.get('transcript', '')
                }, room=sid)
                print(f"[{sid}] User transcript: {data.get('transcript', '')[:50]}...")

            elif event_type == "response.done":
                await sio.emit('response_done', data, room=sid)
                print(f"[{sid}] Response done")

            elif event_type == "error":
                await sio.emit('error', data, room=sid)
                print(f"[{sid}] Error: {data}")

    except websockets.exceptions.ConnectionClosed:
        print(f"[{sid}] WebSocket connection closed")
    except Exception as e:
        print(f"[{sid}] Error handling messages: {e}")
        await sio.emit('error', {'message': str(e)}, room=sid)


@sio.event
async def connect(sid, environ):
    """Handle client connection"""
    print(f"Client connected: {sid}")
    await sio.emit('connected', {'sid': sid}, room=sid)


@sio.event
async def disconnect(sid):
    """Handle client disconnection"""
    print(f"Client disconnected: {sid}")

    # Close Azure OpenAI connection if exists
    if sid in active_connections:
        try:
            await active_connections[sid].close()
        except:
            pass
        del active_connections[sid]

    # Cancel the listening task
    if sid in active_tasks:
        active_tasks[sid].cancel()
        del active_tasks[sid]


@sio.event
async def start_session(sid, data):
    """Start a new realtime session with Azure OpenAI"""
    print(f"[{sid}] Starting session...")

    if not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_API_KEY:
        await sio.emit('error', {
            'message': 'Azure OpenAI credentials not configured. Please set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY environment variables.'
        }, room=sid)
        return

    try:
        url = get_realtime_url()
        print(f"[{sid}] Connecting to: {url}")

        # Connect to Azure OpenAI Realtime API
        ws = await websockets.connect(
            url,
            additional_headers={
                "api-key": AZURE_OPENAI_API_KEY
            }
        )

        active_connections[sid] = ws

        # Start listening for messages
        task = asyncio.create_task(handle_realtime_messages(sid, ws))
        active_tasks[sid] = task

        # Configure the session
        # Get voice configuration options from client
        temperature = data.get("temperature", VOICE_CONFIG["temperature"]["default"])
        max_tokens = data.get("max_response_output_tokens", VOICE_CONFIG["max_response_output_tokens"]["default"])

        # Validate temperature range
        temperature = max(VOICE_CONFIG["temperature"]["min"],
                         min(VOICE_CONFIG["temperature"]["max"], float(temperature)))

        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": data.get("instructions", "You are a helpful AI assistant. Respond naturally and conversationally."),
                "voice": data.get("voice", "alloy"),
                "temperature": temperature,
                "max_response_output_tokens": max_tokens if max_tokens != "inf" else "inf",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500
                }
            }
        }

        await ws.send(json.dumps(session_config))
        print(f"[{sid}] Session configured with voice={data.get('voice', 'alloy')}, temperature={temperature}")

    except Exception as e:
        print(f"[{sid}] Error starting session: {e}")
        await sio.emit('error', {'message': f'Failed to connect: {str(e)}'}, room=sid)


@sio.event
async def send_audio(sid, data):
    """Send audio data to Azure OpenAI"""
    if sid not in active_connections:
        return

    try:
        ws = active_connections[sid]
        audio_data = data.get('audio', '')

        # Send audio to the input buffer
        message = {
            "type": "input_audio_buffer.append",
            "audio": audio_data
        }
        await ws.send(json.dumps(message))

    except Exception as e:
        print(f"[{sid}] Error sending audio: {e}")


@sio.event
async def commit_audio(sid, data):
    """Commit the audio buffer and trigger a response"""
    if sid not in active_connections:
        return

    try:
        ws = active_connections[sid]

        # Commit the audio buffer
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

        # Request a response
        await ws.send(json.dumps({"type": "response.create"}))

    except Exception as e:
        print(f"[{sid}] Error committing audio: {e}")


@sio.event
async def clear_audio_buffer(sid, data):
    """Clear the audio input buffer"""
    if sid not in active_connections:
        return

    try:
        ws = active_connections[sid]
        await ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
    except Exception as e:
        print(f"[{sid}] Error clearing audio buffer: {e}")


@sio.event
async def end_session(sid, data):
    """End the current session"""
    print(f"[{sid}] Ending session...")

    if sid in active_connections:
        try:
            await active_connections[sid].close()
        except:
            pass
        del active_connections[sid]

    if sid in active_tasks:
        active_tasks[sid].cancel()
        del active_tasks[sid]

    await sio.emit('session_ended', {}, room=sid)


# Serve static files
async def index(request):
    """Serve the main HTML page"""
    return web.FileResponse(Path(__file__).parent / 'static' / 'index.html')


async def static_handler(request):
    """Serve static files"""
    filename = request.match_info['filename']
    filepath = Path(__file__).parent / 'static' / filename
    if filepath.exists():
        return web.FileResponse(filepath)
    return web.Response(status=404)


async def get_voice_config(request):
    """API endpoint to get available voices and configuration options"""
    return web.json_response({
        "voices": AVAILABLE_VOICES,
        "config": VOICE_CONFIG
    })


# Add routes
app.router.add_get('/', index)
app.router.add_get('/static/{filename}', static_handler)
app.router.add_get('/api/voice-config', get_voice_config)


if __name__ == '__main__':
    print("=" * 50)
    print("Azure OpenAI GPT-4o Realtime Audio Chat")
    print("=" * 50)
    print(f"Endpoint: {AZURE_OPENAI_ENDPOINT or 'Not configured'}")
    print(f"Deployment: {AZURE_OPENAI_DEPLOYMENT}")
    print("=" * 50)
    print("Starting server at http://localhost:8080")
    print("=" * 50)

    web.run_app(app, host='0.0.0.0', port=8080)
