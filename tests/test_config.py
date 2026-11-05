"""Tests for inventory_machine.config against the shipped config.ini.example."""
import logging
from datetime import datetime
from pathlib import Path

from inventory_machine.config import get_timestamp, load_config

logger = logging.getLogger(__name__)

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.ini.example"


def test_example_config_reads_strftime_values_without_interpolation_error():
    """The example config holds %Y codes. Every value must read as plain text."""
    cfg = load_config(str(EXAMPLE_CONFIG))
    for section in cfg.sections():
        dict(cfg.items(section))
    fmt = cfg.get("output", "timestamp_format")
    assert fmt == "%Y-%m-%d %H:%M:%S"
    datetime.strptime(get_timestamp(cfg), fmt)
    assert set(cfg.options("models")) == {
        "vision_model",
        "vision_model_fallback",
        "embedding_model",
        "ollama_base_url",
    }
    assert cfg.get("models", "ollama_base_url") == "http://localhost:11434"
    assert cfg.get("models", "vision_model") == "minicpm-v4.5"
    assert cfg.get("models", "vision_model_fallback") == "minicpm-v4.6"
    assert cfg.get("models", "embedding_model") == "qwen3-embedding:0.6b"
    assert not cfg.has_section("litellm")
