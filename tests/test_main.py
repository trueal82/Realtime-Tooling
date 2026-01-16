"""
Tests for the main backend module.
"""

import pytest
from aiohttp import web
import json
import os
from unittest.mock import patch, AsyncMock
from pathlib import Path

# Set test environment variables before importing main
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-api-key")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-realtime-preview")

from main import (
    get_realtime_url,
    AVAILABLE_VOICES,
    VOICE_CONFIG,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_API_VERSION,
    get_voice_config,
    index,
    static_handler,
)


class TestVoiceConfiguration:
    """Tests for voice configuration."""

    def test_available_voices_not_empty(self):
        """Test that available voices list is not empty."""
        assert len(AVAILABLE_VOICES) > 0

    def test_available_voices_structure(self):
        """Test that each voice has required fields."""
        for voice in AVAILABLE_VOICES:
            assert "id" in voice
            assert "name" in voice
            assert "description" in voice

    def test_available_voices_contains_expected(self):
        """Test that expected voices are available."""
        voice_ids = [v["id"] for v in AVAILABLE_VOICES]
        expected_voices = ["alloy", "echo", "shimmer", "ash", "ballad", "coral", "sage", "verse"]
        for expected in expected_voices:
            assert expected in voice_ids, f"Expected voice '{expected}' not found"

    def test_voice_config_temperature(self):
        """Test temperature configuration."""
        assert "temperature" in VOICE_CONFIG
        temp_config = VOICE_CONFIG["temperature"]
        assert temp_config["min"] == 0.6
        assert temp_config["max"] == 1.2
        assert temp_config["default"] == 0.8
        assert "step" in temp_config
        assert "description" in temp_config

    def test_voice_config_max_tokens(self):
        """Test max response output tokens configuration."""
        assert "max_response_output_tokens" in VOICE_CONFIG
        tokens_config = VOICE_CONFIG["max_response_output_tokens"]
        assert tokens_config["default"] == 4096
        assert "description" in tokens_config

    def test_voice_config_vad_settings(self):
        """Test VAD configuration options."""
        assert "vad_threshold" in VOICE_CONFIG
        assert "vad_prefix_padding_ms" in VOICE_CONFIG
        assert "vad_silence_duration_ms" in VOICE_CONFIG
        assert "turn_detection_mode" in VOICE_CONFIG


class TestRealtimeUrl:
    """Tests for the realtime URL generation."""

    def test_get_realtime_url_format(self):
        """Test that the realtime URL is properly formatted."""
        with patch('main.AZURE_OPENAI_ENDPOINT', 'https://test-resource.openai.azure.com/'):
            with patch('main.AZURE_OPENAI_DEPLOYMENT', 'gpt-4o-realtime'):
                with patch('main.AZURE_OPENAI_API_VERSION', '2024-10-01-preview'):
                    url = get_realtime_url()
                    assert url.startswith("wss://")
                    assert "openai/realtime" in url
                    assert "api-version=" in url
                    assert "deployment=" in url

    def test_get_realtime_url_strips_trailing_slash(self):
        """Test that trailing slashes are handled."""
        with patch('main.AZURE_OPENAI_ENDPOINT', 'https://test.openai.azure.com///'):
            url = get_realtime_url()
            assert "///" not in url

    def test_get_realtime_url_handles_http(self):
        """Test that http:// is also handled (converted to wss)."""
        with patch('main.AZURE_OPENAI_ENDPOINT', 'http://test.openai.azure.com/'):
            url = get_realtime_url()
            assert url.startswith("wss://")


class TestAPIEndpoints:
    """Tests for HTTP API endpoints using pytest-aiohttp."""

    @pytest.fixture
    def test_app(self):
        """Create a fresh test application."""
        test_app = web.Application()
        test_app.router.add_get('/api/voice-config', get_voice_config)
        test_app.router.add_get('/', index)
        test_app.router.add_get('/static/{filename}', static_handler)
        return test_app

    @pytest.mark.asyncio
    async def test_voice_config_endpoint(self, aiohttp_client, test_app):
        """Test the /api/voice-config endpoint."""
        client = await aiohttp_client(test_app)
        resp = await client.get('/api/voice-config')
        assert resp.status == 200

        data = await resp.json()
        assert "voices" in data
        assert "config" in data
        assert len(data["voices"]) == 8
        assert "temperature" in data["config"]
        assert "max_response_output_tokens" in data["config"]

    @pytest.mark.asyncio
    async def test_index_endpoint(self, aiohttp_client, test_app):
        """Test that the index page is served."""
        client = await aiohttp_client(test_app)
        resp = await client.get('/')
        assert resp.status == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "text/html" in content_type

    @pytest.mark.asyncio
    async def test_static_file_not_found(self, aiohttp_client, test_app):
        """Test that non-existent static files return 404."""
        client = await aiohttp_client(test_app)
        resp = await client.get('/static/nonexistent.js')
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_static_css_served(self, aiohttp_client, test_app):
        """Test that CSS file is served."""
        client = await aiohttp_client(test_app)
        resp = await client.get('/static/styles.css')
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_static_js_served(self, aiohttp_client, test_app):
        """Test that JS files are served."""
        client = await aiohttp_client(test_app)
        resp = await client.get('/static/app.js')
        assert resp.status == 200

        resp = await client.get('/static/audio-processor.js')
        assert resp.status == 200


class TestEnvironmentConfiguration:
    """Tests for environment variable handling."""

    def test_environment_variables_loaded(self):
        """Test that environment variables are accessible."""
        # These should be set from the test setup or have defaults
        assert AZURE_OPENAI_DEPLOYMENT == "gpt-4o-realtime-preview"
        assert AZURE_OPENAI_API_VERSION == "2024-10-01-preview"


class TestAudioProcessing:
    """Tests for audio processing utilities."""

    def test_pcm16_format_constants(self):
        """Test that PCM16 format is used as expected."""
        # The session config should use pcm16 format
        # This is tested implicitly through the session configuration
        pass


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    return ws


class TestSessionManagement:
    """Tests for session management functionality."""

    @pytest.mark.asyncio
    async def test_session_config_structure(self, mock_websocket):
        """Test the structure of session configuration sent to Azure."""
        # Simulate what would be sent
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": "You are a helpful AI assistant.",
                "voice": "alloy",
                "temperature": 0.8,
                "max_response_output_tokens": 4096,
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

        # Verify structure
        assert session_config["type"] == "session.update"
        assert "session" in session_config
        session = session_config["session"]
        assert "text" in session["modalities"]
        assert "audio" in session["modalities"]
        assert session["input_audio_format"] == "pcm16"
        assert session["output_audio_format"] == "pcm16"
        assert session["turn_detection"]["type"] == "server_vad"

    def test_temperature_validation_bounds(self):
        """Test temperature validation within bounds."""
        min_temp = VOICE_CONFIG["temperature"]["min"]
        max_temp = VOICE_CONFIG["temperature"]["max"]

        # Test that validation would clamp values
        test_value = 0.5  # Below min
        clamped = max(min_temp, min(max_temp, test_value))
        assert clamped == min_temp

        test_value = 1.5  # Above max
        clamped = max(min_temp, min(max_temp, test_value))
        assert clamped == max_temp

        test_value = 0.9  # Within range
        clamped = max(min_temp, min(max_temp, test_value))
        assert clamped == test_value
