# generate_page.py
import configparser
import logging
import sqlite3
from pathlib import Path
from typing import Iterable

from PIL import Image

from config import get_timestamp
from inventory_machine.labels.qrcode import generate_qr_for_sticker  # see note on import path

logger = logging.getLogger(__name__)

DPI = 300
SHEET_W_IN, SHEET_H_IN = 8.5, 11.0
STICKER_IN = 0.5
COLS, ROWS = 10, 8


def generate_sticker_page(
    cfg: configparser.ConfigParser,
    conn: sqlite3.Connection,
    location_ids: Iterable[int] | None = None,
    page_name: str = "8.5x11_sticker_page.png",
) -> Path:
    """
    Input: cfg -- loaded ConfigParser; conn -- DB connection holding qr_labels;
           location_ids -- ids to label (default 1..80).
    Output: path of the sticker-page PNG, written to [paths] qr_output_dir.
    Details:
        Writes one PNG per label plus the assembled page into qr_output_dir
        and inserts one qr_labels row per label. No temp files are created.
    """
    base_url = cfg.get("labels", "qr_base_url").rstrip("/")
    out_dir = Path(cfg.get("paths", "qr_output_dir"))
    out_dir.mkdir(parents=True, exist_ok=True)

    capacity = COLS * ROWS
    ids = list(location_ids) if location_ids is not None else list(range(1, capacity + 1))
    if len(ids) > capacity:
        raise ValueError(f"{len(ids)} labels requested; sheet holds {capacity}")

    pitch = round(STICKER_IN * DPI)  # 150 px per sticker cell
    page = Image.new("RGB", (round(SHEET_W_IN * DPI), round(SHEET_H_IN * DPI)), "white")
    created_at = get_timestamp(cfg)

    for idx, loc_id in enumerate(ids):
        row, col = divmod(idx, COLS)

        url = f"{base_url}/location/{loc_id}"                      # J2
        png_path = out_dir / f"qr_location_{loc_id}.png"
        qr_img = generate_qr_for_sticker(url, png_path).convert("RGB")

        x = col * pitch + (pitch - qr_img.width) // 2
        y = row * pitch + (pitch - qr_img.height) // 2
        page.paste(qr_img, (x, y))

        conn.execute(                                              # J2
            "INSERT INTO qr_labels (location_id, url, image_path, created_at) "
            "VALUES (?, ?, ?, ?)",
            (loc_id, url, str(png_path), created_at),
        )

    conn.commit()
    page_path = out_dir / page_name
    page.save(page_path)
    logger.info("Wrote %d labels and %s", len(ids), page_path)
    return page_path
    # J3: nothing deletes PNGs from the working directory anymore