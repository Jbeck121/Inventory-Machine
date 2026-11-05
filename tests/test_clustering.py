"""
Author: Inventory Machine
Date:   2026

Description:
    Tests HDBSCAN, SQL replacement, Chroma integration, and label retries.
"""
# Imports
import json
import logging
from configparser import ConfigParser
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import numpy as np
import pytest

from inventory_machine.clustering.cluster import (
    _cluster_vectors,
    cluster_items,
    label_clusters,
    run_clustering,
    write_clusters,
)
from inventory_machine.db import Database

# Globals
logger = logging.getLogger(__name__)
SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "option_a_home_organizer.sql"


# Functions
@pytest.fixture
def cfg(tmp_path):
    config = ConfigParser(interpolation=None)
    config.read_dict(
        {
            "database": {"backend": "sqlite", "sqlite_path": str(tmp_path / "inventory.db")},
            "clustering": {"min_cluster_size": "3", "min_samples": "2", "epsilon": "0.0"},
            "models": {
                "vision_model": "primary",
                "vision_model_fallback": "fallback",
                "ollama_base_url": "http://localhost:11434",
            },
            "vision": {"max_retries": "2"},
        }
    )
    return config


@pytest.fixture
def db(cfg):
    database = Database(cfg)
    database.load_schema(str(SCHEMA))
    yield database
    database.get_connection().close()


def insert_item(db, item_id, tags=()):
    db.execute(
        "INSERT INTO items (id, description, confidence_score, date_processed) "
        "VALUES (?, ?, ?, ?)",
        (item_id, "test item", 0.9, "2026-01-01"),
    )
    for tag in tags:
        db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
        tag_id = db.fetch_one("SELECT id FROM tags WHERE name = ?", (tag,))[0]
        db.execute("INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)", (item_id, tag_id))


def synthetic_vectors():
    vectors = {f"tools-{i}": [1, offset] for i, offset in enumerate((0, .01, -.01, .02, -.02))}
    vectors.update(
        {f"kitchen-{i}": [offset, 1] for i, offset in enumerate((0, .01, -.01, .02, -.02))}
    )
    vectors["outlier"] = [-1, 0]
    return vectors


def test_two_clusters_and_one_noise_item(cfg):
    assignments = run_clustering(synthetic_vectors(), cfg)
    assert assignments["outlier"] is None
    assert len({value for value in assignments.values() if value is not None}) == 2
    assert len({assignments[f"tools-{i}"] for i in range(5)}) == 1
    assert len({assignments[f"kitchen-{i}"] for i in range(5)}) == 1
    assert assignments["tools-0"] != assignments["kitchen-0"]


def test_too_few_items_do_not_fit_hdbscan(cfg):
    with patch("inventory_machine.clustering.cluster.hdbscan.HDBSCAN") as model:
        assert run_clustering({"one": [1, 0], "two": [0, 1]}, cfg) == {
            "one": None, "two": None,
        }
    model.assert_not_called()


def test_representatives_rank_probability_then_centroid_distance(cfg):
    vectors = {"one": [1, 0], "two": [1, .1], "three": [1, -.1], "four": [1, .3]}
    with patch("inventory_machine.clustering.cluster.hdbscan.HDBSCAN") as constructor:
        constructor.return_value.fit_predict.return_value = np.array([0, 0, 0, 0])
        constructor.return_value.probabilities_ = [0.5, 0.9, 0.9, 0.9]
        assignments, central = _cluster_vectors(vectors, cfg)
    assert assignments == dict.fromkeys(vectors, 0)
    assert central[0] == ["two", "three", "four"]


def test_replace_prior_clusters_and_leave_noise_null(db):
    for item_id in ("first", "second", "noise"):
        insert_item(db, item_id)
    old_ids = write_clusters(db, {"first": 0, "second": 1, "noise": None})
    assert len(old_ids) == 2
    assert db.fetch_one("SELECT cluster_id FROM items WHERE id = ?", ("noise",)) == (None,)
    new_ids = write_clusters(db, {"first": 2, "second": None, "noise": None})
    assert len(new_ids) == 1
    assert db.fetch_all("SELECT id FROM clusters") == [(new_ids[2],)]
    assert db.fetch_one("SELECT cluster_id FROM items WHERE id = ?", ("first",)) == (new_ids[2],)
    assert db.fetch_one("SELECT cluster_id FROM items WHERE id = ?", ("second",)) == (None,)
    assert db.fetch_one("SELECT cluster_id FROM items WHERE id = ?", ("noise",)) == (None,)


def test_malformed_label_retries_then_writes_label(db, cfg):
    insert_item(db, "hammer", ("hammer", "steel", "hand tool"))
    insert_item(db, "wrench", ("wrench", "hand tool"))
    cluster_ids = write_clusters(db, {"hammer": 0, "wrench": 0})
    chat = Mock(side_effect=["not json", '{"label": "Hand Tools"}'])
    labels = label_clusters(db, cfg, {0: ["hammer", "wrench"]}, cluster_ids, chat=chat)
    assert labels == {0: "Hand Tools"}
    assert db.fetch_one("SELECT label FROM clusters WHERE id = ?", (cluster_ids[0],)) == ("Hand Tools",)
    assert [call.kwargs["model"] for call in chat.call_args_list] == ["primary", "primary"]
    prompt = chat.call_args.kwargs["messages"][0]
    assert "hammer" in prompt["content"] and "wrench" in prompt["content"]
    assert "images" not in prompt
    assert "format" not in chat.call_args.kwargs


def test_failed_label_uses_fallback_and_leaves_null(db, cfg):
    insert_item(db, "first", ("hammer",))
    insert_item(db, "second", ("pan",))
    cluster_ids = write_clusters(db, {"first": 0, "second": 1})
    chat = Mock(side_effect=["{}", "[]", "bad json", '{"label": "Kitchen Pans"}'])
    labels = label_clusters(db, cfg, {0: ["first"], 1: ["second"]}, cluster_ids, chat=chat)
    assert labels == {0: None, 1: "Kitchen Pans"}
    assert [call.kwargs["model"] for call in chat.call_args_list] == [
        "primary", "primary", "fallback", "primary",
    ]
    assert db.fetch_one("SELECT label FROM clusters WHERE id = ?", (cluster_ids[0],)) == (None,)
    assert db.fetch_one("SELECT label FROM clusters WHERE id = ?", (cluster_ids[1],)) == ("Kitchen Pans",)


def test_cluster_label_http_5xx_reraises(db, cfg, monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    insert_item(db, "hammer", ("hammer", "steel"))
    cluster_ids = write_clusters(db, {"hammer": 0})
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, json={"error": {"message": "server error"}})

    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr("inventory_machine.llm_gateway.httpx.Client", factory)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        label_clusters(db, cfg, {0: ["hammer"]}, cluster_ids)
    assert caught.value.response.status_code == 500
    assert len(requests) == 1


def test_cluster_label_default_chat_falls_back(db, cfg, monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg["litellm"] = {
        "base_url": "http://gateway.test:4000/v1",
        "vision_model": "gateway-primary",
        "embedding_model": "qwen3-embedding:0.6b",
    }
    insert_item(db, "hammer", ("hammer", "steel"))
    cluster_ids = write_clusters(db, {"hammer": 0})
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "localhost":
            return httpx.Response(500, json={"error": {"message": "down"}})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"label": "Hand Tools"}'}}]},
        )

    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr("inventory_machine.llm_gateway.httpx.Client", factory)
    labels = label_clusters(db, cfg, {0: ["hammer"]}, cluster_ids)
    assert labels == {0: "Hand Tools"}
    assert [str(req.url) for req in requests] == [
        "http://localhost:11434/v1/chat/completions",
        "http://gateway.test:4000/v1/chat/completions",
    ]
    assert "authorization" not in requests[0].headers
    assert requests[1].headers["Authorization"] == "Bearer test-key"
    assert json.loads(requests[1].content)["model"] == "gateway-primary"


def test_cluster_label_http_5xx_survives_fallback(db, cfg, monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    cfg["litellm"] = {
        "base_url": "http://gateway.test:4000/v1",
        "vision_model": "gateway-primary",
        "embedding_model": "qwen3-embedding:0.6b",
    }
    insert_item(db, "hammer", ("hammer", "steel"))
    cluster_ids = write_clusters(db, {"hammer": 0})
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, json={"error": {"message": "server error"}})

    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr("inventory_machine.llm_gateway.httpx.Client", factory)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        label_clusters(db, cfg, {0: ["hammer"]}, cluster_ids)
    assert caught.value.response.status_code == 500
    assert len(requests) == 2




def test_cluster_items_reads_chroma_and_returns_summary(db, cfg):
    vectors = synthetic_vectors()
    for item_id in vectors:
        insert_item(db, item_id, ("tool",))
    collection = Mock()
    collection.get.return_value = {"ids": list(vectors), "embeddings": list(vectors.values())}
    with patch("inventory_machine.clustering.cluster.get_chroma_collection", return_value=collection), patch(
        "inventory_machine.clustering.cluster.label_clusters", return_value={0: "Hand Tools", 1: "Kitchen Gear"}
    ) as labeler:
        result = cluster_items(db, cfg)
    collection.get.assert_called_once_with(include=["embeddings"])
    assert result["cluster_count"] == 2
    assert result["noise_count"] == 1
    assert result["labels"] == {0: "Hand Tools", 1: "Kitchen Gear"}
    assert all(len(items) == 3 for items in labeler.call_args.args[2].values())
    assert db.fetch_one("SELECT cluster_id FROM items WHERE id = ?", ("outlier",)) == (None,)


def test_cluster_items_second_run_replaces_cluster_rows(db, cfg):
    vectors = synthetic_vectors()
    for item_id in vectors:
        insert_item(db, item_id, ("tool",))
    collection = Mock()
    collection.get.return_value = {
        "ids": list(vectors), "embeddings": list(vectors.values()),
    }
    with patch(
        "inventory_machine.clustering.cluster.get_chroma_collection",
        return_value=collection,
    ), patch(
        "inventory_machine.clustering.cluster.label_clusters", return_value={}
    ):
        first = cluster_items(db, cfg)
        first_ids = {row[0] for row in db.fetch_all("SELECT id FROM clusters")}
        second = cluster_items(db, cfg)
        second_ids = {row[0] for row in db.fetch_all("SELECT id FROM clusters")}
    assert first["cluster_count"] == 2
    assert second["cluster_count"] == 2
    assert len(second_ids) == 2
    assert first_ids.isdisjoint(second_ids)
