"""
Author: LlmConnection
Date:   2026

Description:
    Calls the configured embedding model through Ollama first.
    LiteLLM is an optional fallback when Ollama fails.
    Stores vectors in ChromaDB. Writes a pointer row to embeddings_index.
"""
# Imports
import logging
from configparser import ConfigParser

import chromadb

from inventory_machine.llm_gateway import embed

# Globals
logger = logging.getLogger(__name__)


# Functions
def embed_text(text: str, cfg: ConfigParser) -> list[float]:
    """
    Input: text -- string to embed. cfg -- loaded ConfigParser.
    Output: embedding vector as a list of floats.
    Details:
        Calls the embedding model through Ollama, then LiteLLM if needed.
        The caller builds the input string. This function embeds
        the text that it receives.
    """
    return embed_texts([text], cfg)[0]


def embed_texts(texts: list[str], cfg: ConfigParser) -> list[list[float]]:
    """
    Input: texts -- strings to embed in one batch. cfg -- loaded ConfigParser.
    Output: one embedding vector per input string, in input order.
    Details:
        Calls the configured embedding model once for the batch.
        Uses Ollama first, then optional LiteLLM fallback.
    """
    model = cfg.get("models", "embedding_model")
    try:
        return embed(cfg, model, texts)
    except Exception:
        logger.exception("Batch embedding model call failed")
        raise


def get_chroma_collection(cfg: ConfigParser):
    """
    Input: cfg -- loaded ConfigParser.
    Output: a Chroma collection for inventory item vectors.
    Details:
        Opens a PersistentClient at persist_dir.
        Creates the named collection if it does not exist.
    """
    try:
        persist_dir = cfg.get("chroma", "persist_dir")
        name = cfg.get("chroma", "collection_name")
        client = chromadb.PersistentClient(path=persist_dir)
        return client.get_or_create_collection(name)
    except Exception:
        logger.exception("Failed to open Chroma collection")
        raise


def store_embedding(
    db,
    collection,
    item_id: str,
    vector: list[float],
    model_name: str,
) -> None:
    """
    Input: db -- Database from the data access layer. collection --
        Chroma collection. item_id -- item UUID. vector -- embedding
        values. model_name -- embedding model id.
    Output: None.
    Details:
        Inserts a pointer row into embeddings_index, then upserts the
        vector in Chroma under id=item_id. Inside a Database transaction,
        a Chroma error rolls back the pointer row.
        Does not store the vector in SQL.
    """
    try:
        db.execute(
            "INSERT INTO embeddings_index "
            "(item_id, chroma_collection, chroma_record_id, model_name, dims) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                item_id,
                collection.name,
                item_id,
                model_name,
                len(vector),
            ),
        )
    except Exception:
        logger.exception("Failed to insert embeddings_index pointer row")
        raise
    try:
        collection.upsert(ids=[item_id], embeddings=[vector])
    except Exception:
        logger.exception("Failed to upsert embedding into Chroma")
        raise
