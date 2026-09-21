"""
Author: Richard Baldwin
Date:   2026

Description:
    Pipeline entry point. Owns the RotatingFileHandler logging setup
    every other module's logger writes through. Step-wiring for the
    full 9-step pipeline (walk input, preprocess, vision, embed,
    score, cluster, label, write, print labels) lands here once each
    step's module exists; this file only sets up logging for now.
"""
# Imports
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from inventory_machine.config import load_config, ensure_output_dirs

# Globals
logger = logging.getLogger(__name__)


# Functions
def configure_logging(log_file: str) -> None:
    """
    Input: log_file -- path the RotatingFileHandler writes to.
    Output: None.
    Details:
        Attaches one RotatingFileHandler to the root logger, so every
        module's `logging.getLogger(__name__)` call writes to the
        same file. 5 MB per file, 3 backups kept.
    """
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main() -> None:
    """
    Input: None
    Output: None
    Details:
        Loads config, wires up logging, and creates output
        directories. Full pipeline step-wiring (walk, preprocess,
        vision, embed, score, cluster, label, write, print) is a
        later task once each step's module exists.
    """
    cfg = load_config()
    configure_logging(cfg.get("paths", "log_file"))
    ensure_output_dirs(cfg)
    logger.info("Inventory Machine pipeline started.")


if __name__ == "__main__":
    main()
