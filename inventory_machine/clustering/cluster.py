"""
Author: Richard Baldwin
Date:   2026

Description:
    Groups Chroma vectors, replaces cluster rows, and labels each group.
"""
# Imports
import json
import logging
from configparser import ConfigParser
from typing import Callable

import hdbscan
import numpy as np
from ollama import Client, ResponseError

from inventory_machine.embedding.client import get_chroma_collection

# Globals
logger = logging.getLogger(__name__)


# Functions
def _cluster_vectors(
    vectors: dict[str, list[float]], cfg: ConfigParser
) -> tuple[dict[str, int | None], dict[int, list[str]]]:
    """
    Input: vectors -- item UUIDs and embeddings. cfg -- clustering settings.
    Output: item assignments and up to three central UUIDs per cluster.
    Details:
        Uses Euclidean HDBSCAN after it normalizes vectors.
        Ranks members by membership probability, then by squared
        distance to the normalized centroid.
    """
    item_ids = list(vectors)
    min_cluster_size = cfg.getint("clustering", "min_cluster_size")
    if len(item_ids) < min_cluster_size:
        return {item_id: None for item_id in item_ids}, {}

    matrix = np.asarray([vectors[item_id] for item_id in item_ids], dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normalized = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms != 0)
    model = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=cfg.getint("clustering", "min_samples"),
        cluster_selection_epsilon=cfg.getfloat("clustering", "epsilon"),
        metric="euclidean",
    )
    labels = model.fit_predict(normalized)
    assignments = {
        item_id: (int(label) if label >= 0 else None)
        for item_id, label in zip(item_ids, labels)
    }
    central_items = {}
    for cluster_index in sorted(set(labels) - {-1}):
        members = np.flatnonzero(labels == cluster_index)
        centroid = normalized[members].mean(axis=0)
        distance = np.sum((normalized[members] - centroid) ** 2, axis=1)
        ranked = sorted(
            zip(members, distance),
            key=lambda pair: (
                -model.probabilities_[pair[0]],
                pair[1],
                item_ids[pair[0]],
            ),
        )
        central_items[int(cluster_index)] = [
            item_ids[index] for index, _ in ranked[:3]
        ]
    return assignments, central_items


def run_clustering(vectors: dict[str, list[float]], cfg: ConfigParser) -> dict[str, int | None]:
    """
    Input: vectors -- item UUIDs and embeddings. cfg -- clustering settings.
    Output: cluster index per item, or None for noise.
    Details: Groups normalized vectors by Euclidean distance.
    """
    assignments, _ = _cluster_vectors(vectors, cfg)
    return assignments


def write_clusters(db, assignments: dict[str, int | None]) -> dict[int, int]:
    """
    Input: db -- Database. assignments -- item UUIDs and cluster indexes.
    Output: mapping from cluster index to the new clusters.id.
    Details: Removes earlier assignments and rows before it writes new ones.
    """
    db.execute("UPDATE items SET cluster_id = NULL")
    db.execute("DELETE FROM clusters")
    cluster_ids = {}
    for cluster_index in sorted({value for value in assignments.values() if value is not None}):
        cursor = db.execute("INSERT INTO clusters (label) VALUES (?)", (None,))
        cluster_ids[cluster_index] = cursor.lastrowid
    for item_id, cluster_index in assignments.items():
        if cluster_index is not None:
            db.execute(
                "UPDATE items SET cluster_id = ? WHERE id = ?",
                (cluster_ids[cluster_index], item_id),
            )
    return cluster_ids


def label_clusters(
    db,
    cfg: ConfigParser,
    central_items: dict[int, list[str]],
    cluster_ids: dict[int, int],
    chat: Callable | None = None,
) -> dict[int, str | None]:
    """
    Input: db -- Database. cfg -- model settings. central_items -- three
        representative item UUIDs per cluster. cluster_ids -- SQL row IDs.
        chat -- optional Ollama chat callable for tests.
    Output: cluster index to label or None when all model attempts fail.
    Details: Retries malformed labels on the primary model.
        Tries the fallback once and leaves the SQL label NULL if it fails.
    """
    if not central_items:
        return {}
    client = None
    if chat is None:
        client = Client(host=cfg.get("models", "ollama_base_url"))
        chat = client.chat
    primary = cfg.get("models", "vision_model")
    fallback = cfg.get("models", "vision_model_fallback")
    attempts = [primary] * cfg.getint("vision", "max_retries") + [fallback]
    labels = {}
    try:
        for cluster_index, item_ids in central_items.items():
            tag_groups = []
            for item_id in item_ids[:3]:
                rows = db.fetch_all(
                    "SELECT tags.name FROM item_tags "
                    "JOIN tags ON item_tags.tag_id = tags.id "
                    "WHERE item_tags.item_id = ? ORDER BY tags.name",
                    (item_id,),
                )
                tag_groups.append(", ".join(row[0] for row in rows))
            prompt = (
                "Give a 2-4 word group label for these item tags. "
                "Reply with only a JSON object: {\"label\": \"2-4 word group label\"}.\n"
                + "\n".join(f"Item {i}: {tags}" for i, tags in enumerate(tag_groups, 1))
            )
            labels[cluster_index] = None
            for model in attempts:
                try:
                    response = chat(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        format="json",
                    )
                    data = json.loads(response.message.content)
                    label = data["label"]
                    if not isinstance(label, str) or not 2 <= len(label.split()) <= 4:
                        raise ValueError("Cluster label must contain 2-4 words")
                except Exception as exc:
                    logger.exception("Cluster label call or JSON failed for model %s", model)
                    if isinstance(exc, ResponseError) and 400 <= exc.status_code < 600:
                        raise
                    continue
                db.execute("UPDATE clusters SET label = ? WHERE id = ?", (label, cluster_ids[cluster_index]))
                labels[cluster_index] = label
                break
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.warning("Failed to close Ollama cluster label client")
    return labels


def cluster_items(db, cfg: ConfigParser) -> dict:
    """
    Input: db -- Database. cfg -- Chroma, clustering, and model settings.
    Output: summary with cluster count, noise count, and labels.
    Details: Reads Chroma vectors, replaces clusters, and labels each group.
    """
    collection = get_chroma_collection(cfg)
    records = collection.get(include=["embeddings"])
    embeddings = records["embeddings"]
    vectors = {
        item_id: list(vector)
        for item_id, vector in zip(records["ids"], embeddings)
    }
    assignments, central_items = _cluster_vectors(vectors, cfg)
    cluster_ids = write_clusters(db, assignments)
    labels = label_clusters(db, cfg, central_items, cluster_ids)
    return {
        "cluster_count": len(cluster_ids),
        "noise_count": sum(cluster_index is None for cluster_index in assignments.values()),
        "labels": labels,
    }
