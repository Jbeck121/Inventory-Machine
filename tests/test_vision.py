"""Unit tests for inventory_machine.vision.client. Ollama is mocked."""
import asyncio
import configparser
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from inventory_machine.vision.client import call_vision_model, store_vision_attempt

VALID_VISION = {
    "tags": ["golf", "club", "metal"],
    "description": "A metal golf club with a worn grip.",
    "confidence": 0.91,
}


class FakeDatabase:
    """Records execute calls. Does not open a real database."""

    def __init__(self):
        self.calls = []

    def execute(self, query, params=()):
        self.calls.append((query, params))


def _make_cfg(tmp_path, max_retries=3):
    prompt = tmp_path / "vision_prompt.txt"
    prompt.write_text("Describe the object in this image.", encoding="utf-8")
    cfg = configparser.ConfigParser(interpolation=None)
    cfg["models"] = {
        "vision_model": "minicpm-v4.5",
        "vision_model_fallback": "minicpm-v4.6",
        "ollama_base_url": "http://localhost:11434",
    }
    cfg["vision"] = {
        "max_retries": str(max_retries),
        "prompt_template": str(prompt),
    }
    return cfg


def _chat_response(content):
    return SimpleNamespace(message=SimpleNamespace(content=content))


def _patch_async_client(chat_side_effect):
    mock_instance = AsyncMock()
    mock_instance.chat = AsyncMock(side_effect=chat_side_effect)
    mock_instance.close = AsyncMock()
    return patch(
        "inventory_machine.vision.client.AsyncClient",
        return_value=mock_instance,
    ), mock_instance


def test_valid_json_response_parses_keys(tmp_path):
    cfg = _make_cfg(tmp_path)
    db = FakeDatabase()
    patcher, mock_client = _patch_async_client(
        [_chat_response(json.dumps(VALID_VISION))]
    )
    with patcher:
        result = asyncio.run(
            call_vision_model("unused.jpg", cfg, db, "item-1")
        )
    assert result["tags"] == VALID_VISION["tags"]
    assert result["description"] == VALID_VISION["description"]
    assert result["confidence"] == VALID_VISION["confidence"]
    assert mock_client.chat.call_args.kwargs["format"] == "json"


def test_malformed_then_valid_succeeds_within_max_retries(tmp_path):
    cfg = _make_cfg(tmp_path, max_retries=3)
    db = FakeDatabase()
    patcher, _mock_client = _patch_async_client(
        [
            _chat_response("not json"),
            _chat_response(json.dumps(VALID_VISION)),
        ]
    )
    with patcher:
        result = asyncio.run(
            call_vision_model("unused.jpg", cfg, db, "item-1")
        )
    assert result["tags"] == VALID_VISION["tags"]
    assert result["confidence"] == VALID_VISION["confidence"]
    assert len(db.calls) == 2


def test_exceeding_max_retries_triggers_fallback_model(tmp_path):
    cfg = _make_cfg(tmp_path, max_retries=2)
    db = FakeDatabase()
    models_seen = []

    async def chat_side_effect(model, messages=None, format=None, **kwargs):
        models_seen.append(model)
        if model == "minicpm-v4.5":
            return _chat_response("not json")
        return _chat_response(json.dumps(VALID_VISION))

    patcher, _mock_client = _patch_async_client(chat_side_effect)
    with patcher:
        result = asyncio.run(
            call_vision_model("unused.jpg", cfg, db, "item-1")
        )
    assert result["description"] == VALID_VISION["description"]
    assert models_seen == ["minicpm-v4.5", "minicpm-v4.5", "minicpm-v4.6"]
    assert len(db.calls) == 3
    assert db.calls[-1][1][1] == "minicpm-v4.6"


def test_every_attempt_stores_one_audit_row(tmp_path):
    cfg = _make_cfg(tmp_path, max_retries=3)
    db = FakeDatabase()
    patcher, _mock_client = _patch_async_client(
        [
            _chat_response("{"),
            _chat_response("still not json"),
            _chat_response(json.dumps(VALID_VISION)),
        ]
    )
    with patcher:
        asyncio.run(call_vision_model("unused.jpg", cfg, db, "item-9"))
    assert len(db.calls) == 3
    for index, (_query, params) in enumerate(db.calls, start=1):
        item_id, _model_name, attempt_number, raw_response = params
        assert item_id == "item-9"
        assert attempt_number == index
        assert isinstance(raw_response, str)


def test_store_vision_attempt_writes_pointer_fields_only():
    db = FakeDatabase()
    raw = json.dumps(VALID_VISION)
    asyncio.run(
        store_vision_attempt(db, "item-2", "minicpm-v4.5", 1, raw)
    )
    assert len(db.calls) == 1
    query, params = db.calls[0]
    assert "vision_model_outputs" in query
    assert params == ("item-2", "minicpm-v4.5", 1, raw)
