"""Integration tests for the Option A photo pipeline with external services faked."""
import configparser
import json
import logging
from pathlib import Path

import pytest
from PIL import Image

from inventory_machine.db import Database
from inventory_machine import pipeline, preprocessing, labels
from inventory_machine.scoring import score_item
from inventory_machine.vision.client import VisionModelError

logger = logging.getLogger(__name__)
SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "option_a_home_organizer.sql"


class FakeCollection:
    name = "inventory_items"

    def __init__(self):
        self.vectors = {}

    def upsert(self, ids, embeddings):
        for item_id, vector in zip(ids, embeddings):
            self.vectors[item_id] = vector


def _config(tmp_path):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg["paths"] = {"input_dir": str(tmp_path / "input")}
    cfg["database"] = {"backend": "sqlite", "sqlite_path": str(tmp_path / "items.db")}
    cfg["models"] = {"embedding_model": "qwen3-embedding:0.6b"}
    cfg["confidence"] = {
        "self_report_weight": "0.6", "tag_coherence_weight": "0.4",
        "low_confidence_threshold": "0.5",
    }
    cfg["output"] = {"timestamp_timezone": "utc", "timestamp_format": "%Y-%m-%d %H:%M:%S"}
    cfg["location"] = {"folder_separator": ">"}
    return cfg


def _photos(cfg):
    root = Path(cfg.get("paths", "input_dir"))
    for folder, name in (("garage", "club.jpg"), ("kitchen", "spoon.jpg")):
        path = root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (12, 8), "blue").save(path)


def _install_teammates(monkeypatch):
    prepared = []

    def prepare(image_path, cfg):
        prepared.append(image_path)
        return image_path + ".resized"

    def resolve(db, location_name, cfg):
        row = db.fetch_one(
            "SELECT id FROM locations WHERE name = ? AND parent_location_id IS NULL",
            (location_name,),
        )
        if row:
            return row[0]
        return db.execute("INSERT INTO locations (name) VALUES (?)", (location_name,)).lastrowid

    def write_labels(db, cfg):
        for (location_id,) in db.fetch_all("SELECT DISTINCT location_id FROM items"):
            db.execute(
                "INSERT INTO qr_labels (location_id, label_text, qr_url, qr_image_path) "
                "VALUES (?, ?, ?, ?)",
                (location_id, "location", "http://local/item", "fake.png"),
            )
        return len(db.fetch_all("SELECT DISTINCT location_id FROM items"))

    monkeypatch.setattr(preprocessing, "prepare_image", prepare, raising=False)
    monkeypatch.setattr(preprocessing, "resolve_location_id", resolve, raising=False)
    monkeypatch.setattr(labels, "write_qr_labels", write_labels, raising=False)
    return prepared


def _install_services(monkeypatch):
    collection = FakeCollection()
    monkeypatch.setattr(pipeline, "score_item", lambda tags, confidence, cfg: score_item(
        tags, confidence, cfg, embed=lambda texts, _cfg: [[1.0, 0.0]] * len(texts)
    ))
    monkeypatch.setattr(pipeline, "get_chroma_collection", lambda cfg: collection)
    monkeypatch.setattr(pipeline, "embed_text", lambda text, cfg: [1.0, 0.0])
    monkeypatch.setattr(pipeline, "cluster_items", lambda db, cfg: {
        "cluster_count": 1, "noise_count": 0, "labels": {},
    })
    return collection


def _db(cfg):
    db = Database(cfg)
    db.load_schema(str(SCHEMA))
    return db


def test_pipeline_persists_each_photo_and_reuses_tags_and_locations(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    _photos(cfg)
    db = _db(cfg)
    prepared = _install_teammates(monkeypatch)
    collection = _install_services(monkeypatch)

    async def vision(path, cfg):
        assert path.endswith(".resized")
        description = "Golf club" if "club" in path else "Kitchen spoon"
        raw = json.dumps({"tags": ["Metal", "metal", " Tool "], "description": description, "confidence": 0.8})
        return json.loads(raw), [("minicpm-v4.5", 1, "bad json"), ("minicpm-v4.5", 2, raw)]

    monkeypatch.setattr(pipeline, "call_vision_model", vision)
    result = pipeline.run_pipeline(cfg, db)
    assert result == {"processed": 2, "failed": 0, "cluster_count": 1, "label_count": 2, "run_id": 1}
    assert len(prepared) == 2
    items = db.fetch_all("SELECT id, description, location_id, confidence_score, confidence_flag FROM items ORDER BY description")
    assert len(items) == 2
    assert [row[1] for row in items] == ["Golf club", "Kitchen spoon"]
    assert all(row[3:] == (0.88, "ok") for row in items)
    assert len(db.fetch_all("SELECT id FROM images")) == 2
    expected_images = [
        (photo["file_path"], photo["original_filename"], photo["width_px"], photo["height_px"])
        for photo in preprocessing.collect_input_files(cfg)
    ]
    assert db.fetch_all(
        "SELECT file_path, original_filename, width_px, height_px "
        "FROM images ORDER BY original_filename"
    ) == expected_images
    assert db.fetch_all("SELECT name FROM tags ORDER BY name") == [("metal",), ("tool",)]
    assert len(db.fetch_all("SELECT * FROM item_tags")) == 4
    assert len(db.fetch_all("SELECT * FROM confidence_components")) == 2
    assert len(db.fetch_all("SELECT * FROM embeddings_index")) == 2
    assert set(collection.vectors) == {row[0] for row in items}
    assert db.fetch_all("SELECT item_id, attempt_number FROM vision_model_outputs ORDER BY item_id, attempt_number") == [
        (item_id, number) for item_id in sorted(row[0] for row in items) for number in (1, 2)
    ]
    run = db.fetch_one("SELECT input_dir, config_snapshot, item_count, started_at, finished_at FROM processing_runs WHERE id = ?", (result["run_id"],))
    assert run[0] == cfg.get("paths", "input_dir")
    assert json.loads(run[1])["models"]["embedding_model"] == "qwen3-embedding:0.6b"
    assert run[2] == 2 and run[3] and run[4]
    assert len(db.fetch_all("SELECT * FROM qr_labels")) == 2

    again = pipeline.run_pipeline(cfg, db)
    assert again["processed"] == 2 and again["run_id"] == 2
    assert len(db.fetch_all("SELECT * FROM locations")) == 2
    assert len(db.fetch_all("SELECT * FROM tags")) == 2
    assert len(db.fetch_all("SELECT * FROM processing_runs")) == 2


def test_failed_vision_skips_item_and_counts_failure(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    _photos(cfg)
    db = _db(cfg)
    _install_teammates(monkeypatch)
    _install_services(monkeypatch)

    async def vision(path, cfg):
        if "spoon" in path:
            raise VisionModelError("invalid JSON", [("minicpm-v4.5", 1, "bad")])
        return {"tags": ["metal"], "description": "Golf club", "confidence": 0.8}, [
            ("minicpm-v4.5", 1, "valid")
        ]

    monkeypatch.setattr(pipeline, "call_vision_model", vision)
    result = pipeline.run_pipeline(cfg, db)
    assert result["processed"] == 1 and result["failed"] == 1
    assert db.fetch_one("SELECT COUNT(*) FROM items") == (1,)
    assert db.fetch_one("SELECT COUNT(*) FROM images") == (1,)
    assert db.fetch_one("SELECT COUNT(*) FROM vision_model_outputs") == (1,)
    assert db.fetch_one("SELECT item_count FROM processing_runs") == (1,)


@pytest.mark.parametrize("module,missing,owner", [
    (preprocessing, "prepare_image", "Reece, R2"),
    (preprocessing, "resolve_location_id", "Reece, R3"),
    (labels, "write_qr_labels", "Jesse, J2"),
])
def test_missing_teammate_function_names_owner(tmp_path, monkeypatch, module, missing, owner):
    cfg = _config(tmp_path)
    _photos(cfg)
    db = _db(cfg)
    _install_teammates(monkeypatch)
    _install_services(monkeypatch)

    async def vision(path, cfg):
        return {"tags": ["metal"], "description": "Club", "confidence": 0.8}, []

    monkeypatch.setattr(pipeline, "call_vision_model", vision)
    monkeypatch.delattr(module, missing)
    with pytest.raises(RuntimeError, match=rf"{missing}.*{owner}"):
        pipeline.run_pipeline(cfg, db)
