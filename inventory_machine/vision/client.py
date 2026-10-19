"""
Author: LlmConnection
Date:   2026

Description:
    Calls the configured vision model through Ollama.
    Returns parsed output and raw attempts for storage after the item row exists.
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


class VisionModelError(Exception):
    """A vision call error with its earlier attempts."""

    def __init__(self, message: str, attempts: list[tuple[str, int, str]]):
        super().__init__(message)
        self.attempts = attempts


# Functions
def _parse_vision_json(raw_response: str) -> dict:
    """
    Input: raw_response -- text body from the vision model.
    Output: dict with tags, description, and confidence.
    Details:
        Raises ValueError if the text is not JSON, is not an object,
        or lacks a required key.
    """
    data = json.loads(raw_response)
    if not isinstance(data, dict):
        raise ValueError("Vision model JSON must be an object")
    missing = [key for key in REQUIRED_VISION_KEYS if key not in data]
    if missing:
        raise ValueError(
            "Vision model JSON lacks required key(s): " + ", ".join(missing)
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
        Calls chat with format=json. If the call fails, this method logs
        the error and returns its text for the caller to store.
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
        Inserts one audit row into vision_model_outputs.
        Does not store parsed tags. Logs and raises on an insert error.
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
) -> tuple[dict, list[tuple[str, int, str]]]:
    """
    Input: image_path -- path to the photo. cfg -- loaded ConfigParser.
    Output: parsed vision data and (model, attempt number, raw text) rows.
    Details:
        Retries bad JSON on the primary model, then tries the fallback.
        Raises VisionModelError with all raw attempts if both models fail.
        The caller stores the attempts after it inserts the item.
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
    attempts: list[tuple[str, int, str]] = []
    try:
        while True:
            attempt_number += 1
            raw_response, call_error = await _chat_once(client, model, messages)
            attempts.append((model, attempt_number, raw_response))

            if call_error is not None:
                if model == primary and not fallback_used:
                    logger.warning(
                        "Primary vision model failed. The client tries fallback model %s",
                        fallback,
                    )
                    model = fallback
                    fallback_used = True
                    continue
                logger.warning("Vision model failed after %s attempts", len(attempts))
                raise VisionModelError(str(call_error), attempts) from call_error

            try:
                return _parse_vision_json(raw_response), attempts
            except (json.JSONDecodeError, ValueError) as exc:
                if model == primary and attempt_number < max_retries:
                    logger.warning(
                        "Vision model JSON is invalid on attempt %s. The client retries.",
                        attempt_number,
                    )
                    continue
                if model == primary and not fallback_used:
                    logger.warning(
                        "Primary vision model exceeded retries. The client tries fallback model %s",
                        fallback,
                    )
                    model = fallback
                    fallback_used = True
                    continue
                logger.exception(
                    "Vision model output lacks valid JSON or a required key"
                )
                raise VisionModelError(
                    "Vision model output lacks valid JSON or a required key: "
                    + str(exc), attempts
                ) from exc
    finally:
        try:
            await client.close()
        except Exception:
            logger.warning("Failed to close Ollama vision client")
