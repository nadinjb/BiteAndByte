"""Tests for gemini_client.py — JSON parsing and response handling."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We need to mock genai before importing gemini_client
from unittest.mock import patch, MagicMock

# Patch genai at module level before import
with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
    import gemini_client


# ============================================================================
# JSON parsing
# ============================================================================

class TestParseJson:
    def test_clean_json(self):
        text = '{"item": "חזה עוף", "grams": 200}'
        result = gemini_client._parse_json(text, {"item": "?", "grams": 0})
        assert result["item"] == "חזה עוף"
        assert result["grams"] == 200

    def test_json_with_markdown_fences(self):
        text = '```json\n{"item": "rice", "grams": 150}\n```'
        result = gemini_client._parse_json(text, {"item": "?", "grams": 0})
        assert result["item"] == "rice"
        assert result["grams"] == 150

    def test_json_embedded_in_text(self):
        text = 'Here is the result: {"item": "egg", "grams": 55} and more text'
        result = gemini_client._parse_json(text, {"item": "?", "grams": 0})
        assert result["item"] == "egg"

    def test_invalid_json_returns_fallback(self):
        text = "this is not json at all"
        fallback = {"item": "fallback", "grams": 0}
        result = gemini_client._parse_json(text, fallback)
        assert result["item"] == "fallback"
        assert "_raw" in result

    def test_empty_string(self):
        fallback = {"value": 0}
        result = gemini_client._parse_json("", fallback)
        assert result["value"] == 0

    def test_nested_json(self):
        text = '{"markers": {"glucose_mg_dl": 95, "hdl": null}, "notes": "ok"}'
        result = gemini_client._parse_json(text, {})
        assert result["markers"]["glucose_mg_dl"] == 95
        assert result["markers"]["hdl"] is None

    def test_json_with_triple_backticks_only(self):
        text = '```\n{"a": 1}\n```'
        result = gemini_client._parse_json(text, {"a": 0})
        assert result["a"] == 1
