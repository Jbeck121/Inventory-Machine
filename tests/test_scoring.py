"""Tests for confidence scoring and its SQLite persistence."""
# Imports
import configparser
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from inventory_machine.db import Database
from inventory_machine.embedding.client import embed_texts
from inventory_machine.scoring import (
    compute_confidence,
    score_item,
    store_confidence,
    tag_coherence,
)

# Globals
logger = logging.getLogger(__name__)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "option_a_home_organizer.sql"


# Functions
def make_cfg(tmp_path):
    """Build an in-memory configuration for scoring and SQLite."""
    cfg = configparser.ConfigParser(interpolation=None)
    cfg["confidence"] = {
        "self_report_weight": "0.6",
        "tag_coherence_weight": "0.4",
        "low_confidence_threshold": "0.5",
    }
    cfg["models"] = {
        "embedding_model": "qwen3-embedding:0.6b",
        "ollama_base_url": "http://localhost:11434",
    }
    cfg["database"] = {
        "backend": "sqlite",
        "sqlite_path": str(tmp_path / "inventory.sqlite"),
    }
    return cfg


def test_tag_coherence_boundaries():
    assert tag_coherence([]) == 0.0
    assert tag_coherence([[1.0, 0.0]]) == 1.0
    assert tag_coherence([[1.0, 0.0], [2.0, 0.0]]) == pytest.approx(1.0)
    assert tag_coherence([[1.0, 0.0], [0.0, 1.0]]) == pytest.approx(0.0)
    assert tag_coherence([[1.0, 0.0], [-1.0, 0.0]]) == 0.0
    assert tag_coherence([[0.0, 0.0], [1.0, 0.0]]) == 0.0


def test_hand_computed_weighted_confidence(tmp_path):
    cfg = make_cfg(tmp_path)
    embed = MagicMock(return_value=[[1.0, 0.0], [0.6, 0.8]])
    result = score_item(["Hammer", "HAMMER", "tool", "Tool"], 0.9, cfg, embed=embed)
    embed.assert_called_once_with(["Hammer", "tool"], cfg)
    assert result == {
        "self_report": 0.9,
        "tag_coherence": pytest.approx(0.6),
        "self_report_weight": 0.6,
        "tag_coherence_weight": 0.4,
        "confidence_score": pytest.approx(0.78),
        "confidence_flag": "ok",
    }
    assert compute_confidence(0.9, 0.6, cfg) == pytest.approx(0.78)
    assert compute_confidence(1.4, 0.5, cfg) == pytest.approx(0.8)
    assert compute_confidence(-0.2, 0.5, cfg) == pytest.approx(0.2)


def test_threshold_exactly_is_ok_and_below_is_low(tmp_path):
    cfg = make_cfg(tmp_path)
    embed = MagicMock(return_value=[[1.0, 0.0], [0.5, 0.8660254037844386]])
    at_threshold = score_item(["a", "b"], 0.5, cfg, embed=embed)
    assert at_threshold["confidence_score"] == pytest.approx(0.5)
    assert at_threshold["confidence_flag"] == "ok"

    just_below = score_item(["a", "b"], 0.499, cfg, embed=embed)
    assert just_below["confidence_score"] < 0.5
    assert just_below["confidence_flag"] == "low"


def test_empty_tags_skip_embedding_and_clamp_self_report(tmp_path):
    embed = MagicMock()
    result = score_item([], 2.0, make_cfg(tmp_path), embed=embed)
    embed.assert_not_called()
    assert result["self_report"] == 1.0
    assert result["tag_coherence"] == 0.0
    assert result["confidence_score"] == pytest.approx(0.6)


def test_embed_texts_uses_one_ollama_batch_call(tmp_path):
    cfg = make_cfg(tmp_path)
    client = MagicMock()
    client.embed.return_value.embeddings = [[1.0, 0.0], [0.0, 1.0]]
    with patch("inventory_machine.embedding.client.Client", return_value=client) as constructor:
        vectors = embed_texts(["hammer", "tool"], cfg)
    constructor.assert_called_once_with(host="http://localhost:11434")
    client.embed.assert_called_once_with(model="qwen3-embedding:0.6b", input=["hammer", "tool"])
    client.close.assert_called_once_with()
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


def test_store_confidence_writes_option_a_row(tmp_path):
    cfg = make_cfg(tmp_path)
    db = Database(cfg)
    try:
        db.load_schema(str(SCHEMA_PATH))
        result = score_item(
            ["hammer", "tool"],
            0.9,
            cfg,
            embed=lambda tags, config: [[1.0, 0.0], [0.6, 0.8]],
        )
        db.execute(
            "INSERT INTO items (id, description, confidence_score, confidence_flag, date_processed) "
            "VALUES (?, ?, ?, ?, ?)",
            ("item-7", "Claw hammer", result["confidence_score"], result["confidence_flag"], "2026-10-19"),
        )
        store_confidence(db, "item-7", result)
        row = db.fetch_one(
            "SELECT item_id, self_report, tag_coherence, self_report_weight, "
            "tag_coherence_weight FROM confidence_components WHERE item_id = ?",
            ("item-7",),
        )
        assert row[0] == "item-7"
        assert row[1:] == pytest.approx((0.9, 0.6, 0.6, 0.4))
        assert db.fetch_one("SELECT confidence_score, confidence_flag FROM items WHERE id = ?", ("item-7",)) == (
            pytest.approx(0.78), "ok"
        )
    finally:
        db.get_connection().close()
