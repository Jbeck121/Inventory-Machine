"""
Author: Jesse
Date:   2026

Description:
    Tiles label images onto US Letter pages at 300 DPI. Also lays out
    0.5 in QR-only stickers on one US Letter page.
"""
# Imports
import logging
from configparser import ConfigParser
from pathlib import Path
from typing import Iterable

from PIL import Image

# Globals
logger = logging.getLogger(__name__)

LETTER_DPI = 300
LETTER_WIDTH_IN = 8.5
LETTER_HEIGHT_IN = 11.0
LETTER_MARGIN_IN = 0.25
LABEL_GAP_PX = 8
STICKER_IN = 0.5
STICKER_COLS = 10
STICKER_ROWS = 8


# Functions
def _sheet_grid(label_w: int, label_h: int) -> tuple[int, int]:
    """
    Input: label_w, label_h -- label size in pixels.
    Output: (columns, rows) that fit on one letter page.
    Details:
        Uses a 0.25 in margin and LABEL_GAP_PX between labels.
    """
    page_w = round(LETTER_WIDTH_IN * LETTER_DPI)
    page_h = round(LETTER_HEIGHT_IN * LETTER_DPI)
    margin = round(LETTER_MARGIN_IN * LETTER_DPI)
    usable_w = page_w - 2 * margin
    usable_h = page_h - 2 * margin
    cols = max(1, (usable_w + LABEL_GAP_PX) // (label_w + LABEL_GAP_PX))
    rows = max(1, (usable_h + LABEL_GAP_PX) // (label_h + LABEL_GAP_PX))
    return cols, rows


def _load_label_images(label_paths: list[str]) -> list[Image.Image]:
    """
    Input: label_paths -- PNG paths to tile.
    Output: RGB images in the same order.
    Details:
        Skips a path that cannot be read.
    """
    images = []
    for path in label_paths:
        try:
            with Image.open(path) as src:
                images.append(src.convert("RGB"))
        except OSError:
            logger.warning("Skipping unreadable label image %s", path)
            continue
        except Exception:
            logger.exception("Failed to open label image %s", path)
            raise
    return images


def _render_sheet(
    images: list[Image.Image],
    label_w: int,
    label_h: int,
    cols: int,
    rows: int,
) -> Image.Image:
    """
    Input: images for one page, cell size, and grid shape.
    Output: a white US Letter RGB page with labels pasted in row order.
    """
    page_w = round(LETTER_WIDTH_IN * LETTER_DPI)
    page_h = round(LETTER_HEIGHT_IN * LETTER_DPI)
    margin = round(LETTER_MARGIN_IN * LETTER_DPI)
    page = Image.new("RGB", (page_w, page_h), "white")
    for index, img in enumerate(images):
        row = index // cols
        col = index % cols
        if row >= rows:
            break
        x = margin + col * (label_w + LABEL_GAP_PX)
        y = margin + row * (label_h + LABEL_GAP_PX)
        page.paste(img, (x, y))
    return page


def build_label_sheets(label_paths: list[str], output_dir: str) -> list[str]:
    """
    Input: label_paths -- label PNG paths. output_dir -- sheet directory.
    Output: paths of written label_sheet_<n>.png files, in page order.
    Details:
        US Letter at 300 DPI. 0.25 in margins. Does not delete files
        outside output_dir.
    """
    if not label_paths:
        return []
    out = Path(output_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Could not create sheet directory %s", output_dir)
        raise
    images = _load_label_images(label_paths)
    if not images:
        return []
    label_w, label_h = images[0].size
    cols, rows = _sheet_grid(label_w, label_h)
    per_page = max(1, cols * rows)
    saved = []
    page_num = 1
    for start in range(0, len(images), per_page):
        page = _render_sheet(
            images[start:start + per_page],
            label_w,
            label_h,
            cols,
            rows,
        )
        path = out / f"label_sheet_{page_num}.png"
        try:
            page.save(path)
        except OSError:
            logger.exception("Could not save label sheet %s", path)
            raise
        saved.append(str(path))
        page_num += 1
    return saved


def generate_sticker_page(
    cfg: ConfigParser,
    db,
    location_ids: Iterable[int] | None = None,
    page_name: str = "8.5x11_sticker_page.png",
) -> Path:
    """
    Input: cfg -- [paths] qr_output_dir and [labels] qr_base_url.
        db -- Database. location_ids -- ids to label; default is every
        location that holds an item. page_name -- page file name.
    Output: path of the sticker page PNG in qr_output_dir.
    Details:
        Puts up to 80 QR-only 0.5 in stickers (10 x 8) on one US Letter
        page, with a 0.25 in margin. Writes one PNG per sticker.
        write_qr_labels owns the qr_labels rows, so this function
        writes no rows.
    """
    # Import here: qrcode.py imports this module at load time.
    from inventory_machine.labels.qrcode import generate_qr_for_sticker

    base_url = cfg.get("labels", "qr_base_url").rstrip("/")
    out_dir = Path(cfg.get("paths", "qr_output_dir"))
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Could not create QR output directory %s", out_dir)
        raise
    if location_ids is None:
        rows = db.fetch_all(
            "SELECT DISTINCT location_id FROM items "
            "WHERE location_id IS NOT NULL ORDER BY location_id"
        )
        ids = [row[0] for row in rows]
    else:
        ids = list(location_ids)
    capacity = STICKER_COLS * STICKER_ROWS
    if len(ids) > capacity:
        logger.warning("%s stickers requested; one sheet holds %s", len(ids), capacity)
        raise ValueError(f"{len(ids)} stickers requested; sheet holds {capacity}")
    pitch = round(STICKER_IN * LETTER_DPI)
    margin = round(LETTER_MARGIN_IN * LETTER_DPI)
    page = Image.new(
        "RGB",
        (round(LETTER_WIDTH_IN * LETTER_DPI), round(LETTER_HEIGHT_IN * LETTER_DPI)),
        "white",
    )
    for index, location_id in enumerate(ids):
        row, col = divmod(index, STICKER_COLS)
        url = f"{base_url}/location/{location_id}"
        qr_img = generate_qr_for_sticker(url, out_dir / f"qr_location_{location_id}.png")
        x = margin + col * pitch + (pitch - qr_img.width) // 2
        y = margin + row * pitch + (pitch - qr_img.height) // 2
        page.paste(qr_img, (x, y))
    page_path = out_dir / page_name
    try:
        page.save(page_path)
    except OSError:
        logger.exception("Could not save sticker page %s", page_path)
        raise
    logger.info("Wrote %s stickers and %s", len(ids), page_path)
    return page_path
