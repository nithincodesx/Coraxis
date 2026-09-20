"""Model catalogue discovery.

The parsing and filtering rules are pure functions, so they are tested
directly. The HTTP call itself is exercised through the endpoint tests.

The filtering matters more than it looks: providers list speech, embedding and
moderation models alongside chat models, and offering those in a "pick a model"
dropdown is a trap that produces a confusing failure at run time.
"""

from __future__ import annotations

import pytest

from coraxis.core.errors import ConfigurationError
from coraxis.services.llm.discovery import (
    _catalogue_url,
    _looks_like_chat_model,
    _parse_catalogue,
)


class TestParseCatalogue:
    def test_openai_shape(self) -> None:
        payload = {"object": "list", "data": [{"id": "gpt-oss-120b"}, {"id": "qwen3-32b"}]}
        assert _parse_catalogue(payload) == ["gpt-oss-120b", "qwen3-32b"]

    def test_gemini_shape_strips_prefix(self) -> None:
        """Gemini returns `models/gemini-2.5-flash`; the call needs the bare id."""
        payload = {"models": [{"name": "models/gemini-2.5-flash"}]}
        assert _parse_catalogue(payload) == ["gemini-2.5-flash"]

    def test_both_shapes_in_one_payload(self) -> None:
        payload = {"data": [{"id": "a"}], "models": [{"name": "models/b"}]}
        assert _parse_catalogue(payload) == ["a", "b"]

    def test_ignores_malformed_entries(self) -> None:
        payload = {"data": [{"id": "good"}, {"nope": 1}, "string", None]}
        assert _parse_catalogue(payload) == ["good"]

    @pytest.mark.parametrize("payload", [None, [], "text", 42, {}])
    def test_unexpected_payload_is_empty_not_an_error(self, payload: object) -> None:
        """A provider we have not seen before must not crash the endpoint."""
        assert _parse_catalogue(payload) == []


class TestChatModelFilter:
    @pytest.mark.parametrize(
        "model_id",
        [
            "openai/gpt-oss-120b",
            "llama-3.3-70b-versatile",
            "qwen/qwen3.8-27b",
            "mercury-coder",
            "deepseek-chat",
        ],
    )
    def test_keeps_chat_models(self, model_id: str) -> None:
        assert _looks_like_chat_model(model_id)

    @pytest.mark.parametrize(
        "model_id",
        [
            "whisper-large-v3",
            "whisper-large-v3-turbo",
            "text-embedding-3-small",
            "meta-llama/llama-prompt-guard-2-22m",
            "openai/gpt-oss-safeguard-20b",
            "canopylabs/orpheus-v1-english",
            "dall-e-3",
        ],
    )
    def test_drops_non_chat_models(self, model_id: str) -> None:
        assert not _looks_like_chat_model(model_id)


class TestCatalogueUrl:
    def test_uses_default_base_for_known_provider(self) -> None:
        assert _catalogue_url("groq", "") == "https://api.groq.com/openai/v1/models"

    def test_trailing_slash_does_not_double_up(self) -> None:
        url = _catalogue_url("custom", "https://api.inceptionlabs.ai/v1/")
        assert url == "https://api.inceptionlabs.ai/v1/models"

    def test_gemini_has_its_own_root(self) -> None:
        url = _catalogue_url("gemini", "")
        assert url.startswith("https://generativelanguage.googleapis.com/")
        # Gemini does not use the OpenAI `/v1/models` path.
        assert "/openai/" not in url

    def test_custom_without_base_url_is_a_clear_error(self) -> None:
        """The message has to tell the user what to type, not just that it failed."""
        with pytest.raises(ConfigurationError, match="base URL"):
            _catalogue_url("custom", "")
