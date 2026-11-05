"""Unit tests for Ollama-first chat and embedding with optional LiteLLM."""
import json
import logging
from configparser import ConfigParser

import httpx
import pytest
from inventory_machine.llm_gateway import (
    CONNECT_TIMEOUT,
    GatewayError,
    chat_completion,
    complete_chat,
    embed,
)

logger = logging.getLogger(__name__)

OLLAMA_CHAT = "http://localhost:11434/v1/chat/completions"
OLLAMA_EMBED = "http://localhost:11434/v1/embeddings"
GATEWAY_CHAT = "http://gateway.test:4000/v1/chat/completions"
GATEWAY_EMBED = "http://gateway.test:4000/v1/embeddings"


def _team_models():
    return {
        "vision_model": "minicpm-v4.5",
        "vision_model_fallback": "minicpm-v4.6",
        "embedding_model": "qwen3-embedding:0.6b",
        "ollama_base_url": "http://localhost:11434",
    }


def _litellm_section():
    return {
        "base_url": "http://gateway.test:4000/v1",
        "vision_model": "minicpm-v4.5:latest",
        "vision_model_fallback": "minicpm-v4.6:latest",
        "embedding_model": "qwen3-embedding:0.6b",
    }


def _make_cfg(litellm=True, blank_base_url=False):
    cfg = ConfigParser(interpolation=None)
    cfg["models"] = _team_models()
    if litellm:
        section = _litellm_section()
        if blank_base_url:
            section["base_url"] = ""
        cfg["litellm"] = section
    return cfg


class ScriptedHandler:
    def __init__(self, ollama=None, litellm=None):
        self.ollama = list(ollama or [])
        self.litellm = list(litellm or [])
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host == "localhost":
            item = self.ollama.pop(0)
        else:
            item = self.litellm.pop(0)
        if item == "connect_error":
            raise httpx.ConnectError("Connection refused", request=request)
        return item


def _chat_ok(text="hello"):
    return httpx.Response(
        200, json={"choices": [{"message": {"content": text}}]}
    )


def _embed_ok(vector):
    return httpx.Response(
        200, json={"data": [{"index": 0, "embedding": vector}]}
    )


def _install_sync_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.Client
    timeouts = []

    def factory(*args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr("inventory_machine.llm_gateway.httpx.Client", factory)
    return timeouts


def test_ollama_success_skips_gateway_and_auth(monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    cfg = _make_cfg(litellm=True)
    handler = ScriptedHandler(ollama=[_chat_ok("ok")])
    _install_sync_transport(monkeypatch, handler)
    text, label = complete_chat(
        cfg, "minicpm-v4.5", [{"role": "user", "content": "hi"}], False
    )
    assert text == "ok"
    assert label == "minicpm-v4.5"
    assert len(handler.requests) == 1
    request = handler.requests[0]
    assert str(request.url) == OLLAMA_CHAT
    assert "authorization" not in request.headers
    body = json.loads(request.content)
    assert body["model"] == "minicpm-v4.5"


def test_team_keys_only_uses_ollama(monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    cfg = _make_cfg(litellm=False)
    handler = ScriptedHandler(ollama=[_chat_ok("plain")])
    _install_sync_transport(monkeypatch, handler)
    text = chat_completion(
        cfg, "minicpm-v4.5", [{"role": "user", "content": "hi"}], False
    )
    assert text == "plain"
    assert str(handler.requests[0].url) == OLLAMA_CHAT
    assert "authorization" not in handler.requests[0].headers


def test_ollama_connect_error_uses_gateway(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg = _make_cfg(litellm=True)
    handler = ScriptedHandler(
        ollama=["connect_error"],
        litellm=[_chat_ok("from-gateway")],
    )
    _install_sync_transport(monkeypatch, handler)
    text, label = complete_chat(
        cfg, "minicpm-v4.5", [{"role": "user", "content": "hi"}], True
    )
    assert text == "from-gateway"
    assert label == "litellm/minicpm-v4.5:latest"
    assert [str(req.url) for req in handler.requests] == [
        OLLAMA_CHAT, GATEWAY_CHAT,
    ]
    assert "authorization" not in handler.requests[0].headers
    assert handler.requests[1].headers["Authorization"] == "Bearer test-key"
    body = json.loads(handler.requests[1].content)
    assert body["model"] == "minicpm-v4.5:latest"
    assert body["response_format"] == {"type": "json_object"}


def test_ollama_500_falls_back(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg = _make_cfg(litellm=True)
    handler = ScriptedHandler(
        ollama=[httpx.Response(500, json={"error": {"message": "down"}})],
        litellm=[_chat_ok("recovered")],
    )
    _install_sync_transport(monkeypatch, handler)
    text, label = complete_chat(
        cfg, "minicpm-v4.5", [{"role": "user", "content": "hi"}], False
    )
    assert text == "recovered"
    assert label == "litellm/minicpm-v4.5:latest"
    assert len(handler.requests) == 2


def test_ollama_200_error_body_falls_back(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg = _make_cfg(litellm=True)
    handler = ScriptedHandler(
        ollama=[httpx.Response(200, json={"error": {"message": "overloaded"}})],
        litellm=[_chat_ok("recovered")],
    )
    _install_sync_transport(monkeypatch, handler)
    text, label = complete_chat(
        cfg, "minicpm-v4.5", [{"role": "user", "content": "hi"}], False
    )
    assert text == "recovered"
    assert label == "litellm/minicpm-v4.5:latest"


def test_no_litellm_section_reraises_ollama_error(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg = _make_cfg(litellm=False)
    handler = ScriptedHandler(
        ollama=[httpx.Response(500, json={"error": {"message": "down"}})],
    )
    _install_sync_transport(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        chat_completion(
            cfg, "minicpm-v4.5", [{"role": "user", "content": "hi"}], False
        )
    assert caught.value.response.status_code == 500
    assert len(handler.requests) == 1
    assert str(handler.requests[0].url) == OLLAMA_CHAT


def test_blank_fallback_url_reraises(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg = _make_cfg(litellm=True, blank_base_url=True)
    handler = ScriptedHandler(
        ollama=["connect_error"],
    )
    _install_sync_transport(monkeypatch, handler)
    with pytest.raises(httpx.ConnectError):
        chat_completion(
            cfg, "minicpm-v4.5", [{"role": "user", "content": "hi"}], False
        )
    assert len(handler.requests) == 1


def test_litellm_missing_key_fails_after_ollama_error(monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    cfg = _make_cfg(litellm=True)
    handler = ScriptedHandler(
        ollama=[httpx.Response(500, json={"error": {"message": "down"}})],
    )
    _install_sync_transport(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="LITELLM_API_KEY"):
        chat_completion(
            cfg, "minicpm-v4.5", [{"role": "user", "content": "hi"}], False
        )
    assert len(handler.requests) == 1
    assert str(handler.requests[0].url) == OLLAMA_CHAT


def test_embeddings_fall_back(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg = _make_cfg(litellm=True)
    vector = [0.1, 0.2]
    handler = ScriptedHandler(
        ollama=["connect_error"],
        litellm=[_embed_ok(vector)],
    )
    _install_sync_transport(monkeypatch, handler)
    result = embed(cfg, "qwen3-embedding:0.6b", ["hammer"])
    assert result == [vector]
    assert [str(req.url) for req in handler.requests] == [
        OLLAMA_EMBED, GATEWAY_EMBED,
    ]
    assert handler.requests[1].headers["Authorization"] == "Bearer test-key"
    body = json.loads(handler.requests[1].content)
    assert body["model"] == "qwen3-embedding:0.6b"


def test_vision_fallback_model_maps_to_litellm_fallback(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg = _make_cfg(litellm=True)
    handler = ScriptedHandler(
        ollama=[httpx.Response(503, json={"error": {"message": "busy"}})],
        litellm=[_chat_ok("fb")],
    )
    _install_sync_transport(monkeypatch, handler)
    text, label = complete_chat(
        cfg, "minicpm-v4.6", [{"role": "user", "content": "hi"}], False
    )
    assert text == "fb"
    assert label == "litellm/minicpm-v4.6:latest"
    body = json.loads(handler.requests[1].content)
    assert body["model"] == "minicpm-v4.6:latest"


def test_connect_timeout_is_five_seconds(monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    cfg = _make_cfg(litellm=False)
    handler = ScriptedHandler(ollama=[_chat_ok("ok")])
    timeouts = _install_sync_transport(monkeypatch, handler)
    chat_completion(
        cfg, "minicpm-v4.5", [{"role": "user", "content": "hi"}], False
    )
    assert timeouts
    timeout = timeouts[0]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == CONNECT_TIMEOUT
    assert timeout.read == 300.0


def test_error_body_without_fallback_raises_gateway_error(monkeypatch):
    cfg = _make_cfg(litellm=False)
    handler = ScriptedHandler(
        ollama=[httpx.Response(200, json={"error": {"message": "overloaded"}})],
    )
    _install_sync_transport(monkeypatch, handler)
    with pytest.raises(GatewayError, match="overloaded"):
        chat_completion(
            cfg, "minicpm-v4.5", [{"role": "user", "content": "hi"}], False
        )
