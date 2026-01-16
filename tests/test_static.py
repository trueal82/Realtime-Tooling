"""
Tests for static frontend files.
"""

import pytest
from pathlib import Path


class TestStaticFiles:
    """Tests for static frontend files existence and content."""

    @pytest.fixture
    def static_dir(self):
        """Get the static directory path."""
        return Path(__file__).parent.parent / "static"

    def test_index_html_exists(self, static_dir):
        """Test that index.html exists."""
        assert (static_dir / "index.html").exists()

    def test_styles_css_exists(self, static_dir):
        """Test that styles.css exists."""
        assert (static_dir / "styles.css").exists()

    def test_app_js_exists(self, static_dir):
        """Test that app.js exists."""
        assert (static_dir / "app.js").exists()

    def test_audio_processor_js_exists(self, static_dir):
        """Test that audio-processor.js exists."""
        assert (static_dir / "audio-processor.js").exists()

    def test_index_html_has_required_elements(self, static_dir):
        """Test that index.html contains required elements."""
        content = (static_dir / "index.html").read_text()

        # Check for essential elements
        assert "microphone-select" in content
        assert "speaker-select" in content
        assert "voice-select" in content
        assert "temperature-slider" in content
        assert "start-btn" in content
        assert "stop-btn" in content
        assert "transcript" in content
        assert "techlog" in content
        assert "clear-log-btn" in content
        # Check for filters
        assert "filter-info" in content
        assert "filter-receive" in content
        assert "filter-tool" in content
        # Check for advanced VAD settings
        assert "vad-threshold-slider" in content
        assert "turn-detection-select" in content
        # Check for local socket.io reference (not CDN)
        assert "/static/socket.io.min.js" in content
        assert "cdnjs.cloudflare.com" not in content

    def test_socket_io_exists(self, static_dir):
        """Test that socket.io.min.js exists locally."""
        assert (static_dir / "socket.io.min.js").exists()

    def test_app_js_has_realtime_chat_class(self, static_dir):
        """Test that app.js contains the RealtimeChat class."""
        content = (static_dir / "app.js").read_text()

        assert "class RealtimeChat" in content
        assert "loadVoiceConfig" in content
        assert "startSession" in content
        assert "endSession" in content
        assert "socket.emit" in content
        assert "logEvent" in content
        assert "createUserMessagePlaceholder" in content
        assert "clearTechLog" in content
        assert "applyLogFilters" in content
        assert "tool_call" in content

    def test_audio_processor_js_has_worklet(self, static_dir):
        """Test that audio-processor.js contains AudioWorklet processor."""
        content = (static_dir / "audio-processor.js").read_text()

        assert "AudioWorkletProcessor" in content
        assert "registerProcessor" in content
        assert "audio-processor" in content

    def test_styles_css_has_required_classes(self, static_dir):
        """Test that styles.css contains required CSS classes."""
        content = (static_dir / "styles.css").read_text()

        assert ".settings-panel" in content
        assert ".transcript" in content
        assert ".message" in content
        assert ".btn" in content
        assert ".status-indicator" in content

    def test_no_external_resources_in_html(self, static_dir):
        """Test that index.html doesn't load external resources."""
        content = (static_dir / "index.html").read_text()

        # Should not have any external CDN or URL references
        assert "https://" not in content
        assert "http://" not in content
        assert "//cdn" not in content
        assert "//cdnjs" not in content

    def test_no_external_resources_in_css(self, static_dir):
        """Test that styles.css doesn't load external resources."""
        content = (static_dir / "styles.css").read_text()

        # Should not have any external imports or URLs
        assert "https://" not in content
        assert "http://" not in content
        assert "@import" not in content or "url(" not in content


class TestTemplateEnv:
    """Tests for environment template file."""

    @pytest.fixture
    def template_path(self):
        """Get the template.env path."""
        return Path(__file__).parent.parent / "template.env"

    def test_template_env_exists(self, template_path):
        """Test that template.env exists."""
        assert template_path.exists()

    def test_template_env_has_required_vars(self, template_path):
        """Test that template.env contains required variables."""
        content = template_path.read_text()

        assert "AZURE_OPENAI_ENDPOINT" in content
        assert "AZURE_OPENAI_API_KEY" in content
        assert "AZURE_OPENAI_DEPLOYMENT" in content
        assert "AZURE_OPENAI_API_VERSION" in content

    def test_template_env_no_secrets(self, template_path):
        """Test that template.env doesn't contain actual secrets."""
        content = template_path.read_text()

        # Check that the values are empty (just placeholders)
        lines = content.split('\n')
        for line in lines:
            if line.startswith('AZURE_OPENAI_ENDPOINT='):
                value = line.split('=', 1)[1].strip()
                assert value == "" or value.startswith('#'), "Endpoint should be empty in template"
            if line.startswith('AZURE_OPENAI_API_KEY='):
                value = line.split('=', 1)[1].strip()
                assert value == "" or value.startswith('#'), "API key should be empty in template"
