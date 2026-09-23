"""
Author: LlmConnection
Date:   2026

Description:
    Calls the configured vision model through Ollama. Parses JSON
    tags, description, and confidence. Writes each raw attempt to
    vision_model_outputs.
"""
# Imports
import json
import logging
from configparser import ConfigParser
from pathlib import Path

from ollama import AsyncClient

# Globals
logger = logging.getLogger(__name__)

REQUIRED_VISION_KEYS = ("tags", "description", "confidence")


# Functions
def _parse_vision_json(raw_response: str) -> dict:
    """
    Input: raw_response -- text body from the vision model.
    Output: dict with tags, description, and confidence.
    Details:
        Raises ValueError when the text is not JSON, is not an object,
        or is missing a required key.
    """
    data = json.loads(raw_response)
    if not isinstance(data, dict):
        raise ValueError("Vision model JSON must be an object")
    missing = [key for key in REQUIRED_VISION_KEYS if key not in data]
    if missing:
        raise ValueError(
            "Vision model JSON is missing required key(s): " + ", ".join(missing)
        )
    tags = data["tags"]
    if not isinstance(tags, list):
        raise ValueError("Vision model JSON key 'tags' must be a list")
    description = data["description"]
    if not isinstance(description, str):
        raise ValueError("Vision model JSON key 'description' must be a string")
    try:
        confidence = float(data["confidence"])
    except (TypeError, ValueError):
        logger.exception("Vision model JSON key 'confidence' is not a number")
        raise ValueError("Vision model JSON key 'confidence' must be a number")
    return {
        "tags": [str(tag) for tag in tags],
        "description": description,
        "confidence": confidence,
    }


async def _chat_once(client: AsyncClient, model: str, messages: list[dict]) -> tuple[str, Exception | None]:
    """
    Input: client -- Ollama AsyncClient. model -- model tag.
        messages -- chat messages, including the image.
    Output: (raw text, error or None).
    Details:
        Calls chat with format=json. On a call error, logs the error
        and returns the error text so the caller can store the attempt.
    """
    try:
        response = await client.chat(model=model, messages=messages, format="json")
        content = response.message.content
        if content is None:
            return "", None
        return str(content), None
    except Exception as exc:
        logger.exception("Ollama vision chat failed for model %s", model)
        return str(exc), exc


async def store_vision_attempt(
    db,
    item_id: str,
    model_name: str,
    attempt_number: int,
    raw_response: str,
) -> None:
    """
    Input: db -- Database from the data access layer. item_id -- item
        UUID. model_name -- Ollama model tag. attempt_number -- 1-based
        attempt index. raw_response -- raw model text for this attempt.
    Output: None.
    Details:
        Inserts one audit row into vision_model_outputs. Does not store
        the parsed tags. Raises after a log when the insert fails.
    """
    try:
        db.execute(
            "INSERT INTO vision_model_outputs "
            "(item_id, model_name, attempt_number, raw_response) "
            "VALUES (?, ?, ?, ?)",
            (item_id, model_name, attempt_number, raw_response),
        )
    except Exception:
        logger.exception("Failed to store vision model attempt")
        raise


async def call_vision_model(
    image_path: str,
    cfg: ConfigParser,
    db,
    item_id: str,
) -> dict:
    """
    Input: image_path -- path to the photo. cfg -- loaded ConfigParser.
        db -- Database from the data access layer. item_id -- item UUID.
    Output: dict with tags, description, and confidence.
    Details:
        Calls the primary vision model with format=json. Retries on bad
        JSON up to max_retries. Then tries the fallback model once. A
        primary call error also switches to the fallback model once.
        Stores every raw attempt before parse.
    """
    prompt_path = cfg.get("vision", "prompt_template")
    try:
        prompt_text = Path(prompt_path).read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read vision prompt template")
        raise

    messages = [
        {
            "role": "user",
            "content": prompt_text,
            "images": [image_path],
        }
    ]
    primary = cfg.get("models", "vision_model")
    fallback = cfg.get("models", "vision_model_fallback")
    max_retries = cfg.getint("vision", "max_retries")
    host = cfg.get("models", "ollama_base_url")

    client = AsyncClient(host=host)
    model = primary
    fallback_used = False
    attempt_number = 0
    try:
        while True:
            attempt_number += 1
            raw_response, call_error = await _chat_once(client, model, messages)
            await store_vision_attempt(
                db, item_id, model, attempt_number, raw_response
            )

            if call_error is not None:
                if model == primary and not fallback_used:
                    logger.warning(
                        "Primary vision model failed. Trying fallback model %s",
                        fallback,
                    )
                    model = fallback
                    fallback_used = True
                    continue
                raise call_error

            try:
                return _parse_vision_json(raw_response)
            except (json.JSONDecodeError, ValueError) as exc:
                if model == primary and attempt_number < max_retries:
                    logger.warning(
                        "Vision model JSON is not valid on attempt %s. Retrying.",
                        attempt_number,
                    )
                    continue
                if model == primary and not fallback_used:
                    logger.warning(
                        "Primary vision model exceeded retries. Trying fallback model %s",
                        fallback,
                    )
                    model = fallback
                    fallback_used = True
                    continue
                logger.exception(
                    "Vision model output is not valid JSON or is missing a required key"
                )
                raise ValueError(
                    "Vision model output is not valid JSON or is missing a required key: "
                    + str(exc)
                ) from exc
    finally:
        try:
            await client.close()
        except Exception:
            logger.warning("Failed to close Ollama vision client")
