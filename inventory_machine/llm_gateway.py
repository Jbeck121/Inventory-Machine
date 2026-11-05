"""
Author: LlmConnection
Date:   2026

Description:
    Shared HTTP helpers for OpenAI-compatible chat and embeddings.
    Each request uses Ollama first. LiteLLM is an optional fallback.
"""
# Imports
import logging
import os
from configparser import ConfigParser

import httpx

# Globals
logger = logging.getLogger(__name__)

CHAT_TIMEOUT = 300.0
EMBED_TIMEOUT = 60.0
CONNECT_TIMEOUT = 5.0
API_KEY_ENV = "LITELLM_API_KEY"


class GatewayError(RuntimeError):
    """The model server returned an error body or an invalid payload."""


# Functions
def ollama_v1_url(cfg: ConfigParser) -> str:
    """
    Input: cfg -- loaded ConfigParser.
    Output: Ollama OpenAI base URL with no trailing slash.
    Details: Reads [models] ollama_base_url and appends /v1.
    """
    return cfg.get("models", "ollama_base_url").rstrip("/") + "/v1"


def litellm_enabled(cfg: ConfigParser) -> bool:
    """
    Input: cfg -- loaded ConfigParser.
    Output: True when [litellm] base_url is set.
    """
    if not cfg.has_section("litellm"):
        return False
    return bool(cfg.get("litellm", "base_url", fallback="").strip())


def litellm_url(cfg: ConfigParser) -> str:
    """
    Input: cfg -- loaded ConfigParser.
    Output: LiteLLM base URL with no trailing slash.
    """
    return cfg.get("litellm", "base_url").strip().rstrip("/")


def mapped_litellm_model(cfg: ConfigParser, model: str) -> str:
    """
    Input: cfg -- loaded ConfigParser. model -- [models] model id.
    Output: matching [litellm] model id.
    Details:
        Maps vision_model, vision_model_fallback, and embedding_model.
        Missing [litellm] vision_model_fallback uses [litellm] vision_model.
    """
    if (
        cfg.has_option("models", "embedding_model")
        and model == cfg.get("models", "embedding_model")
    ):
        return cfg.get("litellm", "embedding_model")
    if model == cfg.get("models", "vision_model"):
        return cfg.get("litellm", "vision_model")
    if (
        cfg.has_option("models", "vision_model_fallback")
        and model == cfg.get("models", "vision_model_fallback")
    ):
        return cfg.get(
            "litellm",
            "vision_model_fallback",
            fallback=cfg.get("litellm", "vision_model"),
        )
    logger.warning("No LiteLLM mapping for model %s", model)
    return model


def failure_model_label(cfg: ConfigParser, model: str) -> str:
    """
    Input: cfg -- loaded ConfigParser. model -- [models] model id.
    Output: attempt label after a failed call.
    Details: Uses litellm/<id> when LiteLLM is configured.
    """
    if litellm_enabled(cfg):
        return f"litellm/{mapped_litellm_model(cfg, model)}"
    return model


def gateway_headers() -> dict[str, str]:
    """
    Input: none. Reads LITELLM_API_KEY from the environment.
    Output: Authorization header for LiteLLM.
    Details:
        Raises RuntimeError if the key is missing or blank.
        Does not log the key.
    """
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        logger.warning("%s is not set", API_KEY_ENV)
        raise RuntimeError(f"{API_KEY_ENV} is not set")
    return {"Authorization": f"Bearer {key}"}


def build_chat_payload(
    model: str, messages: list, json_mode: bool
) -> dict:
    """
    Input: model -- model id. messages -- chat messages.
        json_mode -- if True, request a JSON object.
    Output: POST body for /chat/completions.
    """
    payload = {"model": model, "messages": messages}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def extract_message_text(body: dict) -> str:
    """
    Input: body -- JSON object from /chat/completions.
    Output: assistant text from content, or from reasoning_content.
    Details:
        Raises GatewayError if the body has an error field or no message.
    """
    if isinstance(body, dict) and "error" in body:
        raise GatewayError(f"Model server returned an error: {body['error']}")
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Chat body lacks a message")
        raise GatewayError("Model server response has no message") from exc
    content = message.get("content")
    text = content.strip() if isinstance(content, str) else ""
    if text:
        return text
    reasoning = message.get("reasoning_content")
    return reasoning.strip() if isinstance(reasoning, str) else ""


def _json_body(response: httpx.Response) -> dict:
    """
    Input: response -- HTTP response from a model server.
    Output: parsed JSON object.
    Details:
        Raises on a non-2xx status. Treats an error field as a failed call.
    """
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError:
        logger.exception("Model server response is not JSON")
        raise
    if isinstance(body, dict) and "error" in body:
        raise GatewayError(f"Model server returned an error: {body['error']}")
    return body


def _chat_timeout() -> httpx.Timeout:
    """
    Input: none.
    Output: chat timeout with a 5 second connect limit.
    """
    return httpx.Timeout(CHAT_TIMEOUT, connect=CONNECT_TIMEOUT)


def _embed_timeout() -> httpx.Timeout:
    """
    Input: none.
    Output: embedding timeout with a 5 second connect limit.
    """
    return httpx.Timeout(EMBED_TIMEOUT, connect=CONNECT_TIMEOUT)


def _prepare_litellm(
    cfg: ConfigParser, model: str, exc: Exception
) -> tuple[str, dict[str, str]] | None:
    """
    Input: cfg -- loaded ConfigParser. model -- [models] model id.
        exc -- error from the Ollama request.
    Output: (LiteLLM model id, headers), or None when fallback is off.
    Details: Logs the Ollama error. Requires LITELLM_API_KEY when enabled.
    """
    if not litellm_enabled(cfg):
        logger.warning("Ollama request failed: %s", exc)
        return None
    logger.warning(
        "Ollama request failed (%s). The client tries LiteLLM.",
        exc,
    )
    mapped = mapped_litellm_model(cfg, model)
    return mapped, gateway_headers()


def _post_json(
    url: str,
    payload: dict,
    timeout: httpx.Timeout,
    headers: dict[str, str] | None = None,
) -> dict:
    """
    Input: url -- POST URL. payload -- JSON body. timeout -- httpx timeout.
        headers -- extra headers, or None.
    Output: parsed JSON object.
    """
    kwargs = {"url": url, "json": payload}
    if headers:
        kwargs["headers"] = headers
    with httpx.Client(timeout=timeout) as client:
        response = client.post(**kwargs)
        return _json_body(response)


async def _async_post_json(
    url: str,
    payload: dict,
    timeout: httpx.Timeout,
    headers: dict[str, str] | None = None,
) -> dict:
    """
    Input: url -- POST URL. payload -- JSON body. timeout -- httpx timeout.
        headers -- extra headers, or None.
    Output: parsed JSON object.
    """
    kwargs = {"url": url, "json": payload}
    if headers:
        kwargs["headers"] = headers
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(**kwargs)
        return _json_body(response)


def _vectors_from_body(body: dict) -> list[list[float]]:
    """
    Input: body -- JSON object from /embeddings.
    Output: one vector per input, ordered by the data index field.
    """
    try:
        rows = body["data"]
        ordered = sorted(rows, key=lambda row: row["index"])
        return [list(row["embedding"]) for row in ordered]
    except (KeyError, TypeError) as exc:
        logger.warning("Embedding body lacks vectors")
        raise GatewayError("Embedding response lacks vectors") from exc


def complete_chat(
    cfg: ConfigParser,
    model: str,
    messages: list,
    json_mode: bool,
) -> tuple[str, str]:
    """
    Input: cfg -- loaded ConfigParser. model -- [models] model id.
        messages -- chat messages. json_mode -- request JSON object if True.
    Output: (assistant text, attempt model label).
    Details:
        POST /v1/chat/completions on Ollama with no auth header.
        On transport, HTTP, or error-body failure, POST the same request
        to LiteLLM with the mapped model id when [litellm] is set.
        Timeout is 300 seconds, with a 5 second connect limit.
    """
    timeout = _chat_timeout()
    ollama_url = f"{ollama_v1_url(cfg)}/chat/completions"
    payload = build_chat_payload(model, messages, json_mode)
    try:
        body = _post_json(ollama_url, payload, timeout)
        return extract_message_text(body), model
    except (httpx.RequestError, httpx.HTTPStatusError, GatewayError) as exc:
        target = _prepare_litellm(cfg, model, exc)
        if target is None:
            raise
        mapped, headers = target
        litellm_payload = build_chat_payload(mapped, messages, json_mode)
        fallback_url = f"{litellm_url(cfg)}/chat/completions"
        body = _post_json(fallback_url, litellm_payload, timeout, headers)
        return extract_message_text(body), f"litellm/{mapped}"


async def async_complete_chat(
    cfg: ConfigParser,
    model: str,
    messages: list,
    json_mode: bool,
) -> tuple[str, str]:
    """
    Input: cfg -- loaded ConfigParser. model -- [models] model id.
        messages -- chat messages. json_mode -- request JSON object if True.
    Output: (assistant text, attempt model label).
    Details:
        Async POST /v1/chat/completions on Ollama with no auth header.
        On transport, HTTP, or error-body failure, POST the same request
        to LiteLLM with the mapped model id when [litellm] is set.
        Timeout is 300 seconds, with a 5 second connect limit.
    """
    timeout = _chat_timeout()
    ollama_url = f"{ollama_v1_url(cfg)}/chat/completions"
    payload = build_chat_payload(model, messages, json_mode)
    try:
        body = await _async_post_json(ollama_url, payload, timeout)
        return extract_message_text(body), model
    except (httpx.RequestError, httpx.HTTPStatusError, GatewayError) as exc:
        target = _prepare_litellm(cfg, model, exc)
        if target is None:
            raise
        mapped, headers = target
        litellm_payload = build_chat_payload(mapped, messages, json_mode)
        fallback_url = f"{litellm_url(cfg)}/chat/completions"
        body = await _async_post_json(
            fallback_url, litellm_payload, timeout, headers
        )
        return extract_message_text(body), f"litellm/{mapped}"


def chat_completion(
    cfg: ConfigParser,
    model: str,
    messages: list,
    json_mode: bool,
) -> str:
    """
    Input: cfg -- loaded ConfigParser. model -- [models] model id.
        messages -- chat messages. json_mode -- request JSON object if True.
    Output: assistant message text.
    Details: Uses Ollama first, then optional LiteLLM fallback.
    """
    text, _label = complete_chat(cfg, model, messages, json_mode)
    return text


def embed(
    cfg: ConfigParser, model: str, inputs: list[str]
) -> list[list[float]]:
    """
    Input: cfg -- loaded ConfigParser. model -- [models] embedding id.
        inputs -- strings to embed.
    Output: one vector per input, ordered by the data index field.
    Details:
        POST /v1/embeddings on Ollama with no auth header.
        On transport, HTTP, or error-body failure, POST the same request
        to LiteLLM with the mapped model id when [litellm] is set.
        Timeout is 60 seconds, with a 5 second connect limit.
    """
    timeout = _embed_timeout()
    ollama_url = f"{ollama_v1_url(cfg)}/embeddings"
    payload = {"model": model, "input": inputs}
    try:
        body = _post_json(ollama_url, payload, timeout)
        return _vectors_from_body(body)
    except (httpx.RequestError, httpx.HTTPStatusError, GatewayError) as exc:
        target = _prepare_litellm(cfg, model, exc)
        if target is None:
            raise
        mapped, headers = target
        litellm_payload = {"model": mapped, "input": inputs}
        fallback_url = f"{litellm_url(cfg)}/embeddings"
        body = _post_json(fallback_url, litellm_payload, timeout, headers)
        return _vectors_from_body(body)
