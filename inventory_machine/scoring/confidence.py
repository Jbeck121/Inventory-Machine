"""
Author: Richard Baldwin
Date:   2026

Description:
    Scores inventory items from model self-report and tag similarity.
"""
# Imports
import logging
from configparser import ConfigParser

import numpy as np

from inventory_machine.config import get_confidence_weights
from inventory_machine.embedding.client import embed_texts

# Globals
logger = logging.getLogger(__name__)


# Functions
def tag_coherence(tag_vectors: list[list[float]]) -> float:
    """
    Input: tag_vectors -- embedding vectors for one item's distinct tags.
    Output: mean pairwise cosine similarity, clamped to [0, 1].
    Details:
        Empty tags score zero. A single tag scores one. A zero-length
        vector has zero similarity with each other vector.
    """
    count = len(tag_vectors)
    if count == 0:
        return 0.0
    if count == 1:
        return 1.0

    vectors = np.asarray(tag_vectors, dtype=float)
    norms = np.linalg.norm(vectors, axis=1)
    total = 0.0
    for i in range(count):
        for j in range(i + 1, count):
            denominator = norms[i] * norms[j]
            if denominator:
                total += float(np.dot(vectors[i], vectors[j]) / denominator)
    return max(0.0, min(1.0, total / (count * (count - 1) // 2)))


def compute_confidence(self_report: float, coherence: float, cfg: ConfigParser) -> float:
    """
    Input: self_report -- model confidence. coherence -- tag similarity.
        cfg -- loaded configuration.
    Output: weighted confidence score.
    Details:
        Clamps the model self-report before applying configured weights.
    """
    self_weight, coherence_weight = get_confidence_weights(cfg)
    return self_weight * max(0.0, min(1.0, self_report)) + coherence_weight * coherence


def score_item(
    tags: list[str], self_report: float, cfg: ConfigParser, embed=embed_texts
) -> dict:
    """
    Input: tags -- model tags. self_report -- model confidence.
        cfg -- loaded configuration. embed -- batch embedding function.
    Output: confidence signals, weights, score, and threshold flag.
    Details:
        Embeds distinct tags once in their original order. Skips the
        model call for an empty tag list.
    """
    distinct_tags = []
    seen = set()
    for tag in tags:
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            distinct_tags.append(tag)
    vectors = embed(distinct_tags, cfg) if distinct_tags else []
    coherence = tag_coherence(vectors)
    clamped_report = max(0.0, min(1.0, self_report))
    self_weight, coherence_weight = get_confidence_weights(cfg)
    score = compute_confidence(clamped_report, coherence, cfg)
    threshold = cfg.getfloat("confidence", "low_confidence_threshold")
    return {
        "self_report": clamped_report,
        "tag_coherence": coherence,
        "self_report_weight": self_weight,
        "tag_coherence_weight": coherence_weight,
        "confidence_score": score,
        "confidence_flag": "low" if score < threshold else "ok",
    }


def store_confidence(db, item_id: str, result: dict) -> None:
    """
    Input: db -- data access layer. item_id -- existing item ID.
        result -- output from score_item.
    Output: None.
    Details:
        Adds one confidence_components row after the caller adds its item.
    """
    try:
        db.execute(
            "INSERT INTO confidence_components "
            "(item_id, self_report, tag_coherence, "
            "self_report_weight, tag_coherence_weight) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                item_id,
                result["self_report"],
                result["tag_coherence"],
                result["self_report_weight"],
                result["tag_coherence_weight"],
            ),
        )
    except Exception:
        logger.exception("Failed to store confidence components for item %s", item_id)
        raise
