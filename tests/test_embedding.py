"""Unit tests for inventory_machine.embedding.client. Ollama is mocked."""
import configparser
from unittest.mock import MagicMock, patch

from inventory_machine.embedding.client import (
    embed_text,
    get_chroma_collection,
    store_embedding,
)


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


def _make_cfg(tmp_path):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg["models"] = {
        "embedding_model": "qwen3-embedding:0.6b",
        "ollama_base_url": "http://localhost:11434",
    }
    cfg["chroma"] = {
        "persist_dir": str(tmp_path / "chroma_store"),
        "collection_name": "inventory_items",
    }
    return cfg


def test_embed_text_returns_mocked_vector_length(tmp_path):
    cfg = _make_cfg(tmp_path)
    vector = [0.11, 0.22, 0.33, 0.44, 0.55]
    mock_instance = MagicMock()
    mock_instance.embed.return_value.embeddings = [vector]
    with patch(
        "inventory_machine.embedding.client.Client",
        return_value=mock_instance,
    ):
        result = embed_text("wooden hammer tool", cfg)
    assert result == vector
    assert len(result) == len(vector)


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
