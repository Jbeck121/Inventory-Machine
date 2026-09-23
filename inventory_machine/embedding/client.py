"""
Author: LlmConnection
Date:   2026

Description:
    Calls the configured embedding model through Ollama. Stores
    vectors in ChromaDB. Writes a pointer row to embeddings_index.
"""
# Imports
import logging
from configparser import ConfigParser

import chromadb
from ollama import Client

# Globals
logger = logging.getLogger(__name__)


# Functions
def embed_text(text: str, cfg: ConfigParser) -> list[float]:
    """
    Input: text -- string to embed. cfg -- loaded ConfigParser.
    Output: embedding vector as a list of floats.
    Details:
        Calls the embedding model through the Ollama embed API. The
        caller builds the input string. This function embeds the text
        it receives.
    """
    model = cfg.get("models", "embedding_model")
    host = cfg.get("models", "ollama_base_url")
    client = Client(host=host)
    try:
        response = client.embed(model=model, input=text)
        return list(response.embeddings[0])
    except Exception:
        logger.exception("Embedding model call failed")
        raise
    finally:
        try:
            client.close()
        except Exception:
            logger.warning("Failed to close Ollama embedding client")


def get_chroma_collection(cfg: ConfigParser):
    """
    Input: cfg -- loaded ConfigParser.
    Output: a Chroma collection for inventory item vectors.
    Details:
        Opens a PersistentClient at persist_dir. Creates the named
        collection when it does not exist.
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
        values. model_name -- Ollama embedding model tag.
    Output: None.
    Details:
        Upserts the vector into Chroma under id=item_id. Inserts a
        pointer row into embeddings_index. Does not store the vector
        in SQL.
    """
    try:
        collection.upsert(ids=[item_id], embeddings=[vector])
    except Exception:
        logger.exception("Failed to upsert embedding into Chroma")
        raise
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
