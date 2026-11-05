"""Unit tests for inventory_machine.vision.client with a mocked model server."""
import asyncio
import base64
import configparser
import json
import logging

import httpx
import pytest

from inventory_machine.vision.client import (
    VisionModelError, call_vision_model, store_vision_attempt,
)

logger = logging.getLogger(__name__)

VALID_VISION = {
    "tags": ["golf", "club", "metal"],
    "description": "A metal golf club with a worn grip.",
    "confidence": 0.91,
}

OLLAMA_CHAT = "http://localhost:11434/v1/chat/completions"
GATEWAY_CHAT = "http://gateway.test:4000/v1/chat/completions"


class FakeDatabase:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=()):
        self.calls.append((query, params))


class ScriptedHandler:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if item == "connect_error":
            raise httpx.ConnectError("Connection refused", request=request)
        return item


def _make_cfg(tmp_path, max_retries=3, json_mode=True, litellm=False):
    prompt = tmp_path / "vision_prompt.txt"
    prompt.write_text("Describe the object in this image.", encoding="utf-8")
    cfg = configparser.ConfigParser(interpolation=None)
    cfg["models"] = {
        "vision_model": "minicpm-v4.5",
        "vision_model_fallback": "minicpm-v4.6",
        "embedding_model": "qwen3-embedding:0.6b",
        "ollama_base_url": "http://localhost:11434",
    }
    cfg["vision"] = {
        "max_retries": str(max_retries),
        "prompt_template": str(prompt),
        "json_mode": "true" if json_mode else "false",
    }
    if litellm:
        cfg["litellm"] = {
            "base_url": "http://gateway.test:4000/v1",
            "vision_model": "minicpm-v4.5:latest",
            "vision_model_fallback": "minicpm-v4.6:latest",
            "embedding_model": "qwen3-embedding:0.6b",
        }
    return cfg


def _write_image(tmp_path, name="unused.jpg", data=b"fake-jpeg-bytes"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _chat_response(content=None, reasoning=None):
    message = {}
    if content is not None:
        message["content"] = content
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return httpx.Response(200, json={"choices": [{"message": message}]})


def _install_async_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(
        "inventory_machine.llm_gateway.httpx.AsyncClient", factory
    )


def _run_vision(
    monkeypatch, tmp_path, responses, max_retries=3, image_name="unused.jpg",
    image_data=b"fake-jpeg-bytes", json_mode=True, litellm=False,
):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg = _make_cfg(
        tmp_path, max_retries=max_retries, json_mode=json_mode, litellm=litellm,
    )
    image = _write_image(tmp_path, name=image_name, data=image_data)
    handler = ScriptedHandler(responses)
    _install_async_transport(monkeypatch, handler)
    result = asyncio.run(call_vision_model(image, cfg))
    return result, handler, image


def test_valid_json_response_parses_keys(tmp_path, monkeypatch):
    (result, handler, _) = _run_vision(
        monkeypatch, tmp_path, [_chat_response(json.dumps(VALID_VISION))],
    )
    parsed, attempts = result
    assert parsed == VALID_VISION
    assert attempts == [("minicpm-v4.5", 1, json.dumps(VALID_VISION))]
    body = json.loads(handler.requests[0].content)
    assert body["response_format"] == {"type": "json_object"}


def test_sends_data_uri_and_json_response_format(tmp_path, monkeypatch):
    image_data = b"jpeg-bytes"
    (_, handler, _) = _run_vision(
        monkeypatch, tmp_path, [_chat_response(json.dumps(VALID_VISION))],
        image_data=image_data,
    )
    request = handler.requests[0]
    assert str(request.url) == OLLAMA_CHAT
    assert "authorization" not in request.headers
    body = json.loads(request.content)
    assert body["model"] == "minicpm-v4.5"
    assert body["response_format"] == {"type": "json_object"}
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Describe the object in this image."}
    uri = parts[1]["image_url"]["url"]
    encoded = base64.b64encode(image_data).decode("ascii")
    assert uri == f"data:image/jpeg;base64,{encoded}"


def test_malformed_then_valid_succeeds_within_max_retries(tmp_path, monkeypatch):
    (result, handler, _) = _run_vision(
        monkeypatch, tmp_path,
        [_chat_response("not json"), _chat_response(json.dumps(VALID_VISION))],
        litellm=True,
    )
    parsed, attempts = result
    assert parsed == VALID_VISION
    assert [raw for _, _, raw in attempts] == ["not json", json.dumps(VALID_VISION)]
    assert [str(req.url) for req in handler.requests] == [OLLAMA_CHAT, OLLAMA_CHAT]
    assert [model for model, _, _ in attempts] == ["minicpm-v4.5", "minicpm-v4.5"]


def test_exceeding_max_retries_triggers_fallback_model(tmp_path, monkeypatch):
    (result, handler, _) = _run_vision(
        monkeypatch, tmp_path,
        [
            _chat_response("not json"),
            _chat_response("not json"),
            _chat_response(json.dumps(VALID_VISION)),
        ],
        max_retries=2,
    )
    parsed, attempts = result
    assert parsed["description"] == VALID_VISION["description"]
    models_seen = [json.loads(req.content)["model"] for req in handler.requests]
    assert models_seen == [
        "minicpm-v4.5", "minicpm-v4.5", "minicpm-v4.6",
    ]
    assert [model for model, _, _ in attempts] == models_seen


def test_every_attempt_returns_one_audit_tuple(tmp_path, monkeypatch):
    (_, attempts) = _run_vision(
        monkeypatch, tmp_path,
        [
            _chat_response("{"),
            _chat_response("still not json"),
            _chat_response(json.dumps(VALID_VISION)),
        ],
    )[0]
    assert len(attempts) == 3
    assert [number for _, number, _ in attempts] == [1, 2, 3]
    assert all(isinstance(raw, str) for _, _, raw in attempts)


def test_total_failure_carries_attempts(tmp_path, monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg = _make_cfg(tmp_path, max_retries=1)
    image = _write_image(tmp_path)
    handler = ScriptedHandler([_chat_response("{"), _chat_response("bad")])
    _install_async_transport(monkeypatch, handler)
    with pytest.raises(VisionModelError) as caught:
        asyncio.run(call_vision_model(image, cfg))
    assert caught.value.attempts == [
        ("minicpm-v4.5", 1, "{"), ("minicpm-v4.6", 2, "bad"),
    ]


def test_call_error_falls_back_and_preserves_attempts(tmp_path, monkeypatch):
    (result, _, _) = _run_vision(
        monkeypatch, tmp_path,
        [
            httpx.Response(503, json={"error": {"message": "model unavailable"}}),
            _chat_response(json.dumps(VALID_VISION)),
        ],
    )
    parsed, attempts = result
    assert parsed == VALID_VISION
    assert attempts[0][0] == "minicpm-v4.5"
    assert "503" in attempts[0][2]
    assert attempts[1] == ("minicpm-v4.6", 2, json.dumps(VALID_VISION))


def test_reasoning_content_fallback(tmp_path, monkeypatch):
    (result, _, _) = _run_vision(
        monkeypatch, tmp_path,
        [_chat_response(content="", reasoning=json.dumps(VALID_VISION))],
    )
    parsed, _ = result
    assert parsed == VALID_VISION


def test_http_200_error_body_triggers_fallback(tmp_path, monkeypatch):
    (result, handler, _) = _run_vision(
        monkeypatch, tmp_path,
        [
            httpx.Response(200, json={"error": {"message": "overloaded"}}),
            _chat_response(json.dumps(VALID_VISION)),
        ],
    )
    parsed, attempts = result
    assert parsed == VALID_VISION
    assert json.loads(handler.requests[0].content)["model"] == "minicpm-v4.5"
    assert json.loads(handler.requests[1].content)["model"] == "minicpm-v4.6"
    assert "overloaded" in attempts[0][2]


def test_ollama_connect_error_records_litellm_model(tmp_path, monkeypatch):
    (result, handler, _) = _run_vision(
        monkeypatch, tmp_path,
        ["connect_error", _chat_response(json.dumps(VALID_VISION))],
        litellm=True,
    )
    parsed, attempts = result
    assert parsed == VALID_VISION
    assert attempts == [
        ("litellm/minicpm-v4.5:latest", 1, json.dumps(VALID_VISION)),
    ]
    assert [str(req.url) for req in handler.requests] == [
        OLLAMA_CHAT, GATEWAY_CHAT,
    ]
    assert "authorization" not in handler.requests[0].headers
    assert handler.requests[1].headers["Authorization"] == "Bearer test-key"
    assert json.loads(handler.requests[1].content)["model"] == "minicpm-v4.5:latest"


def test_missing_api_key_raises_after_ollama_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    cfg = _make_cfg(tmp_path, litellm=True)
    image = _write_image(tmp_path)
    down = httpx.Response(500, json={"error": {"message": "down"}})
    handler = ScriptedHandler([down, down])
    _install_async_transport(monkeypatch, handler)
    with pytest.raises(VisionModelError, match="LITELLM_API_KEY"):
        asyncio.run(call_vision_model(image, cfg))
    assert [str(req.url) for req in handler.requests] == [
        OLLAMA_CHAT, OLLAMA_CHAT,
    ]


def test_store_vision_attempt_writes_pointer_fields_only():
    db = FakeDatabase()
    raw = json.dumps(VALID_VISION)
    asyncio.run(store_vision_attempt(db, "item-2", "club.jpg", "minicpm-v4.5", 1, raw))
    assert len(db.calls) == 1
    query, params = db.calls[0]
    assert "vision_model_outputs" in query
    assert "file_path" in query
    assert params == ("item-2", "club.jpg", "minicpm-v4.5", 1, raw)


def test_store_vision_attempt_allows_null_item_id():
    db = FakeDatabase()
    asyncio.run(store_vision_attempt(db, None, "spoon.jpg", "minicpm-v4.5", 1, "bad"))
    query, params = db.calls[0]
    assert params == (None, "spoon.jpg", "minicpm-v4.5", 1, "bad")
