"""Tests for inventory_machine.embedding.client. The tests mock the model server."""
import configparser
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from inventory_machine.embedding.client import (
    embed_text,
    embed_texts,
    get_chroma_collection,
    store_embedding,
)

OLLAMA_EMBED = "http://localhost:11434/v1/embeddings"
GATEWAY_EMBED = "http://gateway.test:4000/v1/embeddings"


class FakeDatabase:
    """Records execute calls. Does not open a real database."""

    def __init__(self):
        self.calls = []

    def execute(self, query, params=()):
        self.calls.append((query, params))


class FakeCollection:
    """Records upserts. Does not open a real Chroma store."""

    def __init__(self, name="inventory_items"):
        self.name = name
        self.upserts = []

    def upsert(self, ids, embeddings):
        self.upserts.append({"ids": ids, "embeddings": embeddings})


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


def _make_cfg(tmp_path, litellm=False):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg["models"] = {
        "embedding_model": "qwen3-embedding:0.6b",
        "ollama_base_url": "http://localhost:11434",
    }
    cfg["chroma"] = {
        "persist_dir": str(tmp_path / "chroma_store"),
        "collection_name": "inventory_items",
    }
    if litellm:
        cfg["litellm"] = {
            "base_url": "http://gateway.test:4000/v1",
            "embedding_model": "qwen3-embedding:0.6b",
            "vision_model": "minicpm-v4.5:latest",
        }
    return cfg


def _install_sync_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr("inventory_machine.llm_gateway.httpx.Client", factory)


def test_embed_text_returns_mocked_vector_length(tmp_path, monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    cfg = _make_cfg(tmp_path)
    vector = [0.11, 0.22, 0.33, 0.44, 0.55]
    handler = ScriptedHandler([
        httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]}),
    ])
    _install_sync_transport(monkeypatch, handler)
    result = embed_text("wooden hammer tool", cfg)
    assert result == vector
    assert len(result) == len(vector)
    body = json.loads(handler.requests[0].content)
    assert body["model"] == "qwen3-embedding:0.6b"
    assert body["input"] == ["wooden hammer tool"]
    assert str(handler.requests[0].url) == OLLAMA_EMBED
    assert "authorization" not in handler.requests[0].headers


def test_embed_texts_sorts_by_index(tmp_path, monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    cfg = _make_cfg(tmp_path)
    handler = ScriptedHandler([
        httpx.Response(200, json={
            "data": [
                {"index": 1, "embedding": [0.0, 1.0]},
                {"index": 0, "embedding": [1.0, 0.0]},
            ]
        }),
    ])
    _install_sync_transport(monkeypatch, handler)
    result = embed_texts(["a", "b"], cfg)
    assert result == [[1.0, 0.0], [0.0, 1.0]]
    body = json.loads(handler.requests[0].content)
    assert body["input"] == ["a", "b"]
    assert str(handler.requests[0].url) == OLLAMA_EMBED


def test_embeddings_fall_back_to_litellm(tmp_path, monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg = _make_cfg(tmp_path, litellm=True)
    handler = ScriptedHandler([
        "connect_error",
        httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]}),
    ])
    _install_sync_transport(monkeypatch, handler)
    result = embed_text("hammer", cfg)
    assert result == [1.0]
    assert [str(req.url) for req in handler.requests] == [
        OLLAMA_EMBED, GATEWAY_EMBED,
    ]
    assert handler.requests[1].headers["Authorization"] == "Bearer test-key"


def test_missing_api_key_raises_after_ollama_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    cfg = _make_cfg(tmp_path, litellm=True)
    handler = ScriptedHandler(["connect_error"])
    _install_sync_transport(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="LITELLM_API_KEY"):
        embed_text("hammer", cfg)
    assert len(handler.requests) == 1
    assert str(handler.requests[0].url) == OLLAMA_EMBED


def test_store_embedding_sql_params_are_pointers_only():
    db = FakeDatabase()
    collection = FakeCollection(name="inventory_items")
    vector = [0.1, 0.2, 0.3, 0.4]
    store_embedding(
        db,
        collection,
        "item-7",
        vector,
        "qwen3-embedding:0.6b",
    )
    assert collection.upserts == [
        {"ids": ["item-7"], "embeddings": [vector]}
    ]
    assert len(db.calls) == 1
    query, params = db.calls[0]
    assert "embeddings_index" in query
    assert params == (
        "item-7",
        "inventory_items",
        "item-7",
        "qwen3-embedding:0.6b",
        4,
    )
    assert vector not in params
    for value in params:
        assert value is not vector
        assert not isinstance(value, list)


def test_get_chroma_collection_uses_config_names(tmp_path):
    cfg = _make_cfg(tmp_path)
    fake_collection = FakeCollection(name="inventory_items")
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = fake_collection
    with patch(
        "inventory_machine.embedding.client.chromadb.PersistentClient",
        return_value=mock_client,
    ) as mock_cls:
        result = get_chroma_collection(cfg)
    mock_cls.assert_called_once_with(path=cfg.get("chroma", "persist_dir"))
    mock_client.get_or_create_collection.assert_called_once_with(
        "inventory_items"
    )
    assert result is fake_collection
