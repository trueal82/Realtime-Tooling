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

# Available voices for GPT-4o Realtime (gpt-realtime-2025-08-28)
# Reference: https://learn.microsoft.com/en-us/azure/ai-services/openai/realtime-audio-reference
AVAILABLE_VOICES = [
    {"id": "alloy", "name": "Alloy", "description": "Neutral, balanced, versatile"},
    {"id": "ash", "name": "Ash", "description": "Warm, conversational, friendly"},
    {"id": "ballad", "name": "Ballad", "description": "Expressive, dramatic, storytelling"},
    {"id": "coral", "name": "Coral", "description": "Clear, informative, professional"},
    {"id": "echo", "name": "Echo", "description": "Smooth, calm, reassuring"},
    {"id": "sage", "name": "Sage", "description": "Wise, thoughtful, authoritative"},
    {"id": "shimmer", "name": "Shimmer", "description": "Bright, energetic, enthusiastic"},
    {"id": "verse", "name": "Verse", "description": "Versatile, adaptive, dynamic"},
]

# Voice/Session configuration options for gpt-realtime-2025-08-28
VOICE_CONFIG = {
    "temperature": {
        "type": "range",
        "min": 0.6,
        "max": 1.2,
        "default": 0.8,
        "step": 0.05,
        "description": "Controls randomness. Lower = focused, higher = creative."
    },
    "max_response_output_tokens": {
        "type": "select",
        "options": [256, 512, 1024, 2048, 4096, "inf"],
        "default": 4096,
        "description": "Maximum tokens in response."
    },
    "vad_threshold": {
        "type": "range",
        "min": 0.0,
        "max": 1.0,
        "default": 0.5,
        "step": 0.05,
        "description": "Voice activity detection sensitivity. Lower = more sensitive."
    },
    "vad_prefix_padding_ms": {
        "type": "range",
        "min": 0,
        "max": 1000,
        "default": 300,
        "step": 50,
        "description": "Audio to include before speech starts (ms)."
    },
    "vad_silence_duration_ms": {
        "type": "range",
        "min": 100,
        "max": 2000,
        "default": 500,
        "step": 50,
        "description": "Silence duration to end speech (ms)."
    },
    "input_audio_noise_reduction": {
        "type": "toggle",
        "default": True,
        "description": "Enable noise reduction on input audio."
    },
    "turn_detection_mode": {
        "type": "select",
        "options": ["server_vad", "none"],
        "default": "server_vad",
        "description": "Turn detection mode. 'none' for manual control."
    }
}

# Standard tool definition - for logging purposes
# Format for OpenAI Realtime API
STANDARD_TOOL = {
    "type": "function",
    "name": "standard",
    "description": "A standard logging function. Call this to log any action you are about to take.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "The action being performed"
            },
            "details": {
                "type": "string",
                "description": "Additional details about the action"
            }
        },
        "required": ["action"]
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
pending_tool_calls: dict[str, list] = {}  # Store tool calls to process after response.done
tool_call_processed: dict[str, bool] = {}  # Track if we've processed a tool call in current turn


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


async def handle_tool_call(sid: str, ws: Any, call_id: str, function_name: str, arguments: str):
    """
    Handle a tool call from the model and send the response.

    Based on the Realtime API documentation:
    1. Model calls the tool
    2. We execute and return the result via conversation.item.create with function_call_output
    3. We trigger response.create to let the model continue
    """
    print(f"[{sid}] ========== HANDLING TOOL CALL ==========")
    print(f"[{sid}] Function: {function_name}")
    print(f"[{sid}] Call ID: {call_id}")
    print(f"[{sid}] Arguments: {arguments}")

    # Emit tool call event to frontend for logging
    await sio.emit('tool_call', {
        'call_id': call_id,
        'name': function_name,
        'arguments': arguments
    }, room=sid)

    # Parse arguments
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        args = {}

    # Execute the standard tool - acknowledge what the model wants to do
    result = {
        "status": "acknowledged",
        "action": args.get("action", ""),
        "details": args.get("details", ""),
        "message": "Action logged. Proceed with your response to the user."
    }
    print(f"[{sid}] Tool result: {result}")

    # Send tool response back to the model via conversation.item.create
    tool_response = {
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(result)
        }
    }
    print(f"[{sid}] Sending function_call_output...")
    await ws.send(json.dumps(tool_response))

    # Emit that we sent the response
    await sio.emit('tool_response', {
        'call_id': call_id,
        'output': result
    }, room=sid)

    # Mark that we've processed a tool call
    tool_call_processed[sid] = True

    # Request the model to continue with audio response
    # IMPORTANT: Set tool_choice to "none" to get audio, not another tool call
    response_request = {
        "type": "response.create",
        "response": {
            "tool_choice": "none"  # Disable tools for follow-up to get audio
        }
    }
    print(f"[{sid}] Requesting model to continue with tool_choice=none (for audio)...")
    await ws.send(json.dumps(response_request))
    print(f"[{sid}] ========== TOOL CALL COMPLETE ==========")


async def handle_realtime_messages(sid: str, ws: Any):
    """Handle incoming messages from Azure OpenAI Realtime API"""
    try:
        async for message in ws:
            data = json.loads(message)
            event_type = data.get("type", "")

            # Log ALL events for debugging (except high-frequency audio deltas)
            if event_type not in ["response.audio.delta", "input_audio_buffer.append"]:
                if "function" in event_type.lower() or "tool" in event_type.lower() or event_type in ["response.output_item.done", "response.done"]:
                    print(f"[{sid}] >>> EVENT: {event_type}")
                    print(f"[{sid}]     {json.dumps(data, indent=2)[:500]}")

            # Handle different event types
            if event_type == "session.created":
                await sio.emit('session_created', data, room=sid)
                print(f"[{sid}] Session created")

            elif event_type == "session.updated":
                await sio.emit('session_updated', data, room=sid)
                # Log the session config that was accepted
                session = data.get('session', {})
                accepted_tool_choice = session.get('tool_choice')
                print(f"[{sid}] Session updated - accepted config:")
                print(f"[{sid}]   - modalities: {session.get('modalities')}")
                print(f"[{sid}]   - voice: {session.get('voice')}")
                print(f"[{sid}]   - tools: {[t.get('name') for t in session.get('tools', [])]}")
                print(f"[{sid}]   - tool_choice: {accepted_tool_choice}")
                print(f"[{sid}]   - tool_choice type: {type(accepted_tool_choice)}")

                # Check if tool_choice was changed by the API
                if accepted_tool_choice == 'auto':
                    print(f"[{sid}]   WARNING: API changed tool_choice to 'auto' - forced tool calls may not work")
                elif isinstance(accepted_tool_choice, dict) and accepted_tool_choice.get('name') == 'standard':
                    print(f"[{sid}]   SUCCESS: tool_choice is forced to 'standard' function")
                else:
                    print(f"[{sid}]   UNEXPECTED tool_choice value")

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

            # Handle TEXT responses (when model responds with text instead of audio)
            elif event_type == "response.text.delta":
                # Text response delta - forward to frontend
                await sio.emit('text_delta', {
                    'role': 'assistant',
                    'delta': data.get('delta', '')
                }, room=sid)

            elif event_type == "response.text.done":
                # Text response complete
                await sio.emit('text_done', {
                    'role': 'assistant',
                    'text': data.get('text', '')
                }, room=sid)
                print(f"[{sid}] Text response done: {data.get('text', '')[:100]}...")

            elif event_type == "response.content_part.done":
                # Content part done - just log it
                part = data.get('part', {})
                print(f"[{sid}] Content part done - type: {part.get('type')}")

            elif event_type == "input_audio_buffer.committed":
                # Audio buffer committed - just log it
                print(f"[{sid}] Audio buffer committed")

            elif event_type == "input_audio_buffer.speech_started":
                await sio.emit('speech_started', data, room=sid)
                print(f"[{sid}] Speech started - NEW TURN")
                # Reset tool call tracking for new turn
                tool_call_processed[sid] = False
                pending_tool_calls[sid] = []
                print(f"[{sid}]   Reset: tool_call_processed=False, pending_tool_calls cleared")
                print(f"[{sid}]   Session tool_choice should still be forced to 'standard'")

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
                # Check for function calls in response
                response = data.get('response', {})
                output = response.get('output', [])
                print(f"[{sid}] ===== RESPONSE.DONE =====")
                print(f"[{sid}] tool_call_processed={tool_call_processed.get(sid, False)}")
                print(f"[{sid}] Output items count: {len(output)}")

                # Log output items
                has_function_call = False
                has_audio = False
                for i, item in enumerate(output):
                    item_type = item.get('type')
                    item_id = item.get('id', f'item_{i}')
                    print(f"[{sid}]   [{i}] type={item_type}, id={item_id}, status={item.get('status')}")

                    if item_type == 'function_call':
                        has_function_call = True
                        print(f"[{sid}]       FUNCTION_CALL: name={item.get('name')}, call_id={item.get('call_id')}")
                    elif item_type == 'message':
                        content = item.get('content', [])
                        print(f"[{sid}]       MESSAGE: content items={len(content)}")
                        for j, c in enumerate(content):
                            c_type = c.get('type')
                            if c_type == 'text':
                                print(f"[{sid}]         [{j}] Text: {c.get('text', '')[:100]}...")
                            elif c_type == 'audio':
                                has_audio = True
                                print(f"[{sid}]         [{j}] Audio transcript: {c.get('transcript', '')[:50]}...")

                # Process any pending tool calls (response is complete, safe to create new one)
                if sid in pending_tool_calls and pending_tool_calls[sid]:
                    print(f"[{sid}] Processing {len(pending_tool_calls[sid])} pending tool call(s)...")
                    for tool_call in pending_tool_calls[sid]:
                        await handle_tool_call(
                            sid, ws,
                            tool_call['call_id'],
                            tool_call['name'],
                            tool_call['arguments']
                        )
                    # Clear the queue
                    pending_tool_calls[sid] = []
                else:
                    print(f"[{sid}] No pending tool calls to process")

                print(f"[{sid}] ===== END RESPONSE.DONE =====")

            elif event_type == "response.function_call_arguments.delta":
                await sio.emit('function_call_delta', data, room=sid)
                print(f"[{sid}] Function call args delta: {data.get('delta', '')[:50]}...")

            elif event_type == "response.function_call_arguments.done":
                await sio.emit('function_call_done', data, room=sid)
                print(f"[{sid}] Function call arguments done:")
                print(f"[{sid}]   - call_id: {data.get('call_id')}")
                print(f"[{sid}]   - name: {data.get('name')}")
                print(f"[{sid}]   - arguments: {data.get('arguments')}")

                # Queue the tool call - will be processed after response.done
                call_id = data.get('call_id')
                function_name = data.get('name')
                arguments = data.get('arguments', '{}')

                if function_name and call_id:
                    if sid not in pending_tool_calls:
                        pending_tool_calls[sid] = []
                    pending_tool_calls[sid].append({
                        'call_id': call_id,
                        'name': function_name,
                        'arguments': arguments
                    })
                    print(f"[{sid}]   >>> Tool call queued, waiting for response.done")

            elif event_type == "response.output_item.done":
                await sio.emit('output_item_done', data, room=sid)
                # Check if this is a function call item - THIS IS WHERE WE DETECT TOOL CALLS
                # Similar to sample code: for item in response.output: if item.type == "function_call"
                item = data.get('item', {})
                item_type = item.get('type')
                print(f"[{sid}] Output item done - type: {item_type}")

                if item_type == 'function_call':
                    call_id = item.get('call_id')
                    function_name = item.get('name')
                    arguments = item.get('arguments', '{}')
                    status = item.get('status')
                    print(f"[{sid}] >>> FUNCTION CALL DETECTED in output_item.done:")
                    print(f"[{sid}]   - name: {function_name}")
                    print(f"[{sid}]   - call_id: {call_id}")
                    print(f"[{sid}]   - status: {status}")
                    print(f"[{sid}]   - arguments: {arguments}")

                    # Queue the tool call to be processed after response.done
                    if function_name and call_id:
                        if sid not in pending_tool_calls:
                            pending_tool_calls[sid] = []
                        # Check if not already queued (might come from function_call_arguments.done too)
                        existing_calls = [tc['call_id'] for tc in pending_tool_calls[sid]]
                        if call_id not in existing_calls:
                            pending_tool_calls[sid].append({
                                'call_id': call_id,
                                'name': function_name,
                                'arguments': arguments
                            })
                            print(f"[{sid}]   >>> Queued tool call for processing after response.done")

            elif event_type == "error":
                await sio.emit('error', data, room=sid)
                error_info = data.get('error', {})
                print(f"[{sid}] ERROR from API:")
                print(f"[{sid}]   - type: {error_info.get('type')}")
                print(f"[{sid}]   - code: {error_info.get('code')}")
                print(f"[{sid}]   - message: {error_info.get('message')}")
                print(f"[{sid}]   - full: {json.dumps(data, indent=2)}")

            else:
                # Log any unhandled event types for debugging
                print(f"[{sid}] Unhandled event type: {event_type}")
                if 'function' in event_type.lower() or 'tool' in event_type.lower():
                    print(f"[{sid}]   TOOL-RELATED: {json.dumps(data, indent=2)}")
                # Forward unhandled events to frontend for visibility
                await sio.emit('unhandled_event', {'type': event_type, 'data': data}, room=sid)

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
        vad_threshold = data.get("vad_threshold", VOICE_CONFIG["vad_threshold"]["default"])
        vad_prefix_padding_ms = data.get("vad_prefix_padding_ms", VOICE_CONFIG["vad_prefix_padding_ms"]["default"])
        vad_silence_duration_ms = data.get("vad_silence_duration_ms", VOICE_CONFIG["vad_silence_duration_ms"]["default"])
        turn_detection_mode = data.get("turn_detection_mode", VOICE_CONFIG["turn_detection_mode"]["default"])

        # Validate temperature range
        temperature = max(VOICE_CONFIG["temperature"]["min"],
                         min(VOICE_CONFIG["temperature"]["max"], float(temperature)))

        # Build turn detection config
        turn_detection = None
        if turn_detection_mode == "server_vad":
            turn_detection = {
                "type": "server_vad",
                "threshold": float(vad_threshold),
                "prefix_padding_ms": int(vad_prefix_padding_ms),
                "silence_duration_ms": int(vad_silence_duration_ms)
            }

        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": data.get("instructions", "You are a helpful AI assistant. IMPORTANT: Before responding to ANY user request, you MUST ALWAYS call the 'standard' function first to log what action you are about to take. Never skip calling the standard function. After calling the function and receiving acknowledgment, proceed with your audio response."),
                "voice": data.get("voice", "alloy"),
                "temperature": temperature,
                "max_response_output_tokens": max_tokens if max_tokens != "inf" else "inf",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": turn_detection,
                "tools": [STANDARD_TOOL],
                "tool_choice": "auto"  # Model decides but instructions encourage tool use
            }
        }

        print(f"[{sid}] Sending session config to API:")
        print(f"[{sid}] {json.dumps(session_config, indent=2)}")
        await ws.send(json.dumps(session_config))
        print(f"[{sid}] Session config sent. Waiting for session.updated...")
        print(f"[{sid}]   - voice: {data.get('voice', 'alloy')}")
        print(f"[{sid}]   - temperature: {temperature}")
        print(f"[{sid}]   - vad_threshold: {vad_threshold}")
        print(f"[{sid}]   - modalities: {session_config['session']['modalities']}")
        print(f"[{sid}]   - tools sent: {[t['name'] for t in session_config['session']['tools']]}")
        print(f"[{sid}]   - tool_choice: auto (model decides, instructions encourage tool use)")

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


@sio.event
async def update_session(sid, data):
    """Update session configuration (voice, temperature, etc.) during an active session"""
    if sid not in active_connections:
        await sio.emit('error', {'message': 'No active session to update'}, room=sid)
        return

    try:
        ws = active_connections[sid]

        # Get configuration options from client
        temperature = data.get("temperature", VOICE_CONFIG["temperature"]["default"])
        max_tokens = data.get("max_response_output_tokens", VOICE_CONFIG["max_response_output_tokens"]["default"])
        vad_threshold = data.get("vad_threshold", VOICE_CONFIG["vad_threshold"]["default"])
        vad_prefix_padding_ms = data.get("vad_prefix_padding_ms", VOICE_CONFIG["vad_prefix_padding_ms"]["default"])
        vad_silence_duration_ms = data.get("vad_silence_duration_ms", VOICE_CONFIG["vad_silence_duration_ms"]["default"])
        turn_detection_mode = data.get("turn_detection_mode", VOICE_CONFIG["turn_detection_mode"]["default"])

        # Validate temperature range
        temperature = max(VOICE_CONFIG["temperature"]["min"],
                         min(VOICE_CONFIG["temperature"]["max"], float(temperature)))

        # Build turn detection config
        turn_detection = None
        if turn_detection_mode == "server_vad":
            turn_detection = {
                "type": "server_vad",
                "threshold": float(vad_threshold),
                "prefix_padding_ms": int(vad_prefix_padding_ms),
                "silence_duration_ms": int(vad_silence_duration_ms)
            }

        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": data.get("instructions", "You are a helpful AI assistant. IMPORTANT: Before responding to ANY user request, you MUST ALWAYS call the 'standard' function first to log what action you are about to take. Never skip calling the standard function. After calling the function and receiving acknowledgment, proceed with your audio response."),
                "voice": data.get("voice", "alloy"),
                "temperature": temperature,
                "max_response_output_tokens": max_tokens if max_tokens != "inf" else "inf",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": turn_detection,
                "tools": [STANDARD_TOOL],
                "tool_choice": "auto"
            }
        }

        print(f"[{sid}] Updating session config:")
        print(f"[{sid}]   - voice: {data.get('voice', 'alloy')}")
        print(f"[{sid}]   - temperature: {temperature}")
        await ws.send(json.dumps(session_config))

        # Emit confirmation to frontend
        await sio.emit('session_update_sent', {
            'voice': data.get('voice', 'alloy'),
            'temperature': temperature,
            'max_response_output_tokens': max_tokens,
            'turn_detection_mode': turn_detection_mode,
            'vad_threshold': vad_threshold,
            'vad_prefix_padding_ms': vad_prefix_padding_ms,
            'vad_silence_duration_ms': vad_silence_duration_ms
        }, room=sid)

    except Exception as e:
        print(f"[{sid}] Error updating session: {e}")
        await sio.emit('error', {'message': f'Failed to update session: {str(e)}'}, room=sid)


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
