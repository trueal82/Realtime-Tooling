"""
Test script to understand Azure OpenAI Realtime API tool call behavior.
This script tests different tool_choice configurations and logs the responses.
"""

import asyncio
import json
import os
from dotenv import load_dotenv
import websockets

# Load environment variables
load_dotenv()

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-realtime-preview")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-01-preview")


def get_realtime_url() -> str:
    endpoint = AZURE_OPENAI_ENDPOINT.rstrip('/')
    if endpoint.startswith('https://'):
        endpoint = endpoint[8:]
    elif endpoint.startswith('http://'):
        endpoint = endpoint[7:]
    return f"wss://{endpoint}/openai/realtime?api-version={AZURE_OPENAI_API_VERSION}&deployment={AZURE_OPENAI_DEPLOYMENT}"


# Standard tool definition
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


async def test_tool_choice(tool_choice_value, description):
    """Test a specific tool_choice configuration"""
    print(f"\n{'='*60}")
    print(f"TEST: {description}")
    print(f"tool_choice: {tool_choice_value}")
    print(f"{'='*60}")

    url = get_realtime_url()
    print(f"Connecting to: {url}")

    try:
        async with websockets.connect(
            url,
            additional_headers={"api-key": AZURE_OPENAI_API_KEY}
        ) as ws:

            # Wait for session.created
            message = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(message)
            print(f"Received: {data.get('type')}")

            # Send session config with tool_choice
            session_config = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": "You are a helpful assistant. Always call the standard function before responding.",
                    "voice": "alloy",
                    "tools": [STANDARD_TOOL],
                    "tool_choice": tool_choice_value,
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "turn_detection": None  # Disable VAD for manual control
                }
            }

            print(f"\nSending session.update with tool_choice: {tool_choice_value}")
            await ws.send(json.dumps(session_config))

            # Wait for session.updated
            message = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(message)
            print(f"Received: {data.get('type')}")

            if data.get('type') == 'session.updated':
                session = data.get('session', {})
                print(f"  Accepted tool_choice: {session.get('tool_choice')}")
                print(f"  Accepted tools: {[t.get('name') for t in session.get('tools', [])]}")

            # Send a text message to trigger a response
            text_message = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Hello, what is 2+2?"
                        }
                    ]
                }
            }
            print(f"\nSending user message: 'Hello, what is 2+2?'")
            await ws.send(json.dumps(text_message))

            # Request a response
            print("Sending response.create...")
            await ws.send(json.dumps({"type": "response.create"}))

            # Collect responses for up to 15 seconds
            print("\nWaiting for responses...")
            start_time = asyncio.get_event_loop().time()
            function_call_detected = False
            response_done = False

            while asyncio.get_event_loop().time() - start_time < 15:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=2)
                    data = json.loads(message)
                    event_type = data.get('type', '')

                    # Log interesting events
                    if event_type in ['response.created', 'response.done',
                                      'response.output_item.done', 'response.output_item.added',
                                      'response.function_call_arguments.done',
                                      'conversation.item.created']:
                        print(f"\n>>> {event_type}")

                        if event_type == 'response.output_item.done':
                            item = data.get('item', {})
                            print(f"    Item type: {item.get('type')}")
                            if item.get('type') == 'function_call':
                                function_call_detected = True
                                print(f"    Function: {item.get('name')}")
                                print(f"    Call ID: {item.get('call_id')}")
                                print(f"    Arguments: {item.get('arguments')}")

                                # Send function response
                                print("\n    Sending function_call_output...")
                                func_response = {
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": item.get('call_id'),
                                        "output": json.dumps({"status": "acknowledged", "result": "logged"})
                                    }
                                }
                                await ws.send(json.dumps(func_response))

                                # Request continuation
                                print("    Sending response.create to continue...")
                                await ws.send(json.dumps({"type": "response.create"}))

                            elif item.get('type') == 'message':
                                content = item.get('content', [])
                                for c in content:
                                    if c.get('type') == 'text':
                                        print(f"    Text: {c.get('text', '')[:100]}...")
                                    elif c.get('type') == 'audio':
                                        print(f"    Audio transcript: {c.get('transcript', '')[:100]}...")

                        if event_type == 'response.function_call_arguments.done':
                            print(f"    Name: {data.get('name')}")
                            print(f"    Arguments: {data.get('arguments')}")

                        if event_type == 'response.done':
                            response = data.get('response', {})
                            output = response.get('output', [])
                            print(f"    Output items: {len(output)}")
                            for i, item in enumerate(output):
                                print(f"      [{i}] type={item.get('type')}")
                            response_done = True

                            # If no function call was made, break
                            if not function_call_detected:
                                break

                    elif event_type == 'error':
                        print(f"\n>>> ERROR: {data.get('error', {}).get('message')}")
                        break

                except asyncio.TimeoutError:
                    if response_done:
                        break
                    continue

            print(f"\n--- RESULT ---")
            print(f"Function call detected: {function_call_detected}")
            print(f"Response done: {response_done}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("="*60)
    print("Azure OpenAI Realtime API Tool Call Test")
    print("="*60)
    print(f"Endpoint: {AZURE_OPENAI_ENDPOINT}")
    print(f"Deployment: {AZURE_OPENAI_DEPLOYMENT}")
    print(f"API Version: {AZURE_OPENAI_API_VERSION}")

    # Test different tool_choice configurations
    test_cases = [
        ("auto", "tool_choice = 'auto' (default)"),
        ("required", "tool_choice = 'required' (force at least one)"),
        ({"type": "function", "name": "standard"}, "tool_choice = forced 'standard' function"),
        ("none", "tool_choice = 'none' (no tools)"),
    ]

    for tool_choice, description in test_cases:
        await test_tool_choice(tool_choice, description)
        await asyncio.sleep(2)  # Brief pause between tests

    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
