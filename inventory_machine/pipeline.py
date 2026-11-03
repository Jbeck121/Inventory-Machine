"""
Author: Richard Baldwin
Date:   2026

Description:
    Runs photo ingestion, inference, relational storage, clustering,
    and QR label generation. Configures file logging for the pipeline.
"""
# Imports
import asyncio
import importlib
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from inventory_machine.config import load_config, ensure_output_dirs, get_timestamp
from inventory_machine.db import Database
from inventory_machine.preprocessing import collect_input_files
from inventory_machine.vision.client import (
    VisionModelError, call_vision_model, store_vision_attempt,
)
from inventory_machine.scoring import score_item, store_confidence
from inventory_machine.embedding.client import (
    embed_text, get_chroma_collection, store_embedding,
)
from inventory_machine.clustering import cluster_items

# Globals
logger = logging.getLogger(__name__)


# Functions
def configure_logging(log_file: str) -> None:
    """
    Input: log_file -- path the RotatingFileHandler writes to.
    Output: None.
    Details:
        Adds one RotatingFileHandler to the root logger.
        Every module's `logging.getLogger(__name__)` call writes to
        the same file. Each file holds 5 MB, with 3 backups.
    """
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def _teammate_function(module_name: str, function_name: str, step: int, owner: str):
    """
    Input: module_name, function_name -- where the function lives.
        step -- pipeline step number. owner -- teammate and task ID.
    Output: the function object.
    Details:
        Raises RuntimeError with the missing function and its owner
        if a teammate's function is not available yet.
    """
    module = importlib.import_module(module_name)
    try:
        return getattr(module, function_name)
    except AttributeError as exc:
        logger.exception("Missing %s.%s (%s)", module_name, function_name, owner)
        raise RuntimeError(
            f"pipeline step {step} needs {module_name}.{function_name} ({owner})"
        ) from exc


def run_pipeline(cfg, db) -> dict:
    """
    Input: cfg -- loaded config. db -- open Database with Option A schema.
    Output: processed, failed, cluster_count, label_count, and run_id.
    Details:
        Inserts the run before it reads photos. Stores each item
        before its dependent rows. Skips photos only if vision fails entirely.
    """
    snapshot = json.dumps({
        section: dict(cfg.items(section)) for section in cfg.sections()
    })
    run_id = db.execute(
        "INSERT INTO processing_runs (input_dir, config_snapshot, started_at) "
        "VALUES (?, ?, ?)",
        (cfg.get("paths", "input_dir"), snapshot, get_timestamp(cfg)),
    ).lastrowid
    processed = 0
    failed = 0
    collection = None
    prepare_image = _teammate_function(
        "inventory_machine.preprocessing", "prepare_image", 2, "Reece, R2"
    )
    resolve_location_id = _teammate_function(
        "inventory_machine.preprocessing", "resolve_location_id", 5, "Reece, R3"
    )
    for photo in collect_input_files(cfg):
        prepared_path = prepare_image(photo["file_path"], cfg)
        try:
            vision, attempts = asyncio.run(call_vision_model(prepared_path, cfg))
        except VisionModelError as exc:
            logger.warning(
                "Vision failed for %s after %s attempts: %s",
                photo["file_path"], len(exc.attempts), exc,
            )
            failed += 1
            continue

        score = score_item(vision["tags"], vision["confidence"], cfg)
        location_id = resolve_location_id(db, photo["location"], cfg)
        item_id = str(uuid4())
        db.execute(
            "INSERT INTO items (id, location_id, description, confidence_score, "
            "confidence_flag, date_processed) VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, location_id, vision["description"],
             score["confidence_score"], score["confidence_flag"], get_timestamp(cfg)),
        )
        for model_name, attempt_number, raw_response in attempts:
            asyncio.run(store_vision_attempt(
                db, item_id, model_name, attempt_number, raw_response
            ))
        db.execute(
            "INSERT INTO images (item_id, file_path, original_filename, width_px, "
            "height_px, date_taken, gps_lat, gps_lon) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, photo["file_path"], photo["original_filename"],
             photo["width_px"], photo["height_px"], photo["date_taken"],
             photo["gps_lat"], photo["gps_lon"]),
        )
        tags = list(dict.fromkeys(tag.strip().lower() for tag in vision["tags"] if tag.strip()))
        for tag in tags:
            tag_row = db.fetch_one("SELECT id FROM tags WHERE name = ?", (tag,))
            if tag_row is None:
                tag_id = db.execute(
                    "INSERT INTO tags (name) VALUES (?)", (tag,)
                ).lastrowid
            else:
                tag_id = tag_row[0]
            db.execute(
                "INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)",
                (item_id, tag_id),
            )
        store_confidence(db, item_id, score)
        if collection is None:
            collection = get_chroma_collection(cfg)
        vector = embed_text(" ".join([*tags, vision["description"]]), cfg)
        store_embedding(
            db, collection, item_id, vector, cfg.get("models", "embedding_model")
        )
        processed += 1

    clusters = cluster_items(db, cfg)
    write_qr_labels = _teammate_function(
        "inventory_machine.labels", "write_qr_labels", 9, "Jesse, J2"
    )
    label_count = write_qr_labels(db, cfg)
    db.execute(
        "UPDATE processing_runs SET item_count = ?, finished_at = ? WHERE id = ?",
        (processed, get_timestamp(cfg), run_id),
    )
    return {
        "processed": processed, "failed": failed,
        "cluster_count": clusters["cluster_count"],
        "label_count": label_count, "run_id": run_id,
    }


def main() -> None:
    """
    Input: None.
    Output: None.
    Details:
        Loads the config and the Option A schema if needed.
        Runs the pipeline against the selected database and prints its summary.
    """
    cfg = load_config()
    configure_logging(cfg.get("paths", "log_file"))
    ensure_output_dirs(cfg)
    db = Database(cfg)
    if not db.table_exists("items"):
        schema_path = Path(__file__).resolve().parent.parent / "schema" / "option_a_home_organizer.sql"
        db.load_schema(str(schema_path))
    summary = run_pipeline(cfg, db)
    logger.info("Inventory Machine run: %s", summary)
    print(summary)


if __name__ == "__main__":
    main()
