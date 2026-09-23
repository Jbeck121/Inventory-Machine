"""
Author: Richard Baldwin
Date:   2026

Description:
    Loads config.ini and validates confidence-weight settings at
    startup. Every other module gets its settings by passing the
    ConfigParser object returned here around; no module re-reads the
    file on its own.
"""
import configparser
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Globals

DEFAULT_CONFIG_PATH = "config.ini"


# Functions
def load_config(path: str = DEFAULT_CONFIG_PATH) -> configparser.ConfigParser:
    """
    Input: path -- location of the .ini file to load.
    Output: a populated ConfigParser.
    Details:
        Raises FileNotFoundError when the file is missing. Also runs
        the confidence-weight check, so a bad config fails at startup,
        not partway through a pipeline run.
    """
    cfg = configparser.ConfigParser(
        interpolation=configparser.BasicInterpolation(),
        inline_comment_prefixes=(";",),
    )
    read_paths = cfg.read(path)
    if not read_paths:
        logger.warning("Config file not found at %s", path)
        raise FileNotFoundError(f"Config not found: {path}")
    get_confidence_weights(cfg)
    return cfg


def get_confidence_weights(cfg: configparser.ConfigParser) -> tuple[float, float]:
    """
    Input: cfg -- a loaded ConfigParser.
    Output: (self_report_weight, tag_coherence_weight).
    Details:
        Raises ValueError when the two weights do not sum to 1.0,
        within a small floating-point tolerance.
    """
    w1 = cfg.getfloat("confidence", "self_report_weight")
    w2 = cfg.getfloat("confidence", "tag_coherence_weight")
    if abs(w1 + w2 - 1.0) > 1e-6:
        logger.warning("Confidence weights do not sum to 1.0: %s + %s", w1, w2)
        raise ValueError(f"Confidence weights must sum to 1.0, got {w1 + w2}")
    return w1, w2


def get_timestamp(cfg: configparser.ConfigParser) -> str:
    """
    Input: cfg -- a loaded ConfigParser.
    Output: the current time, formatted per [output] settings.
    Details:
        [output] timestamp_timezone = utc gives UTC time. Any other
        value gives local time. Named-timezone support (for example
        America/New_York) is a later extension via zoneinfo.ZoneInfo.
    """
    tz = timezone.utc if cfg.get("output", "timestamp_timezone") == "utc" else None
    fmt = cfg.get("output", "timestamp_format")
    return datetime.now(tz).strftime(fmt)


def ensure_output_dirs(cfg: configparser.ConfigParser) -> None:
    """
    Input: cfg -- a loaded ConfigParser.
    Output: None.
    Details:
        Creates the directories [paths] qr_output_dir and the parent
        of [paths] log_file, if they do not already exist. Does not
        create [paths] input_dir -- that one must already hold photos.
    """
    Path(cfg.get("paths", "qr_output_dir")).mkdir(parents=True, exist_ok=True)
    Path(cfg.get("paths", "log_file")).parent.mkdir(parents=True, exist_ok=True)
